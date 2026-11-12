/**
 * 侧边栏结构探查 v3：打印 ha-list-nav 的完整层级（项 / 嵌套子项）
 * 用法: node cdp-sidebar-check.mjs <URL> [宽] [高]
 */
import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const TARGET = process.argv[2] || "http://ha.local:8123/device-cards";
const W = Number(process.argv[3] || 1440);
const H = Number(process.argv[4] || 1200);
const HA_ORIGIN = process.env.HA_ORIGIN || "http://ha.local:8123";
const PORT = 9950 + Math.floor(Math.random() * 40);

const TOKENS = JSON.parse(fs.readFileSync("/tmp/ha_tokens.json", "utf8"));
TOKENS.expires = Date.now() + (TOKENS.expires_in || 1800) * 1000;

const CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const profile = fs.mkdtempSync(path.join(os.tmpdir(), "ha-side-"));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const chrome = spawn(
  CHROME,
  [
    "--headless=new",
    `--remote-debugging-port=${PORT}`,
    `--user-data-dir=${profile}`,
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-gpu",
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--hide-scrollbars",
    "--proxy-server=http://127.0.0.1:7897",
    "--proxy-bypass-list=<-loopback>",
    `--window-size=${W},${H}`,
    "about:blank",
  ],
  { stdio: "ignore", env: { ...process.env, http_proxy: "", https_proxy: "", HTTP_PROXY: "", HTTPS_PROXY: "" } }
);

async function getTarget() {
  for (let i = 0; i < 80; i++) {
    try {
      const r = await fetch(`http://127.0.0.1:${PORT}/json/list`);
      const list = await r.json();
      const page = list.find((t) => t.type === "page");
      if (page) return page;
    } catch (e) {}
    await sleep(250);
  }
  throw new Error("Chrome CDP 未就绪");
}

class CDP {
  constructor(ws) {
    this.ws = ws;
    this.id = 0;
    this.pending = new Map();
    ws.addEventListener("message", (ev) => {
      const m = JSON.parse(ev.data);
      if (m.id && this.pending.has(m.id)) {
        const { resolve, reject } = this.pending.get(m.id);
        this.pending.delete(m.id);
        m.error ? reject(new Error(JSON.stringify(m.error))) : resolve(m.result);
      }
    });
  }
  send(method, params = {}) {
    const id = ++this.id;
    this.ws.send(JSON.stringify({ id, method, params }));
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      setTimeout(() => {
        if (this.pending.has(id)) {
          this.pending.delete(id);
          reject(new Error("timeout " + method));
        }
      }, 45000);
    });
  }
  async eval(expression) {
    const r = await this.send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
    if (r.exceptionDetails) throw new Error(JSON.stringify(r.exceptionDetails).slice(0, 800));
    return r.result.value;
  }
}

const JS = `(() => {
  const dump = (el, depth, out) => {
    if (!el || depth > 8) return;
    let kids = [];
    try {
      kids = [...el.children];
      if (el.shadowRoot) kids = [...el.shadowRoot.children, ...kids];
    } catch (e) { return; }
    for (const k of kids) {
      const tag = k.tagName;
      if (tag === "STYLE" || tag === "SCRIPT") continue;
      const txt = (k.textContent || "").trim().replace(/\\s+/g, " ").slice(0, 60);
      const attrs = {};
      for (const a of k.attributes || []) attrs[a.name] = String(a.value).slice(0, 60);
      out.push({
        d: depth, tag, attrs,
        txt: txt.length > 40 ? "" : txt,
        shadow: !!k.shadowRoot,
      });
      dump(k, depth + 1, out);
    }
  };
  const out = [];
  const sb = document.querySelector("ha-sidebar");
  if (sb) dump(sb, 0, out);
  return out.filter(r => r.tag.startsWith("HA-") || r.tag.startsWith("MUI-") || r.tag === "A" || r.tag === "BUTTON" || r.tag === "LI").slice(0, 80);
})()`;

(async () => {
  const target = await getTarget();
  const ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((r) => ws.addEventListener("open", r, { once: true }));
  const cdp = new CDP(ws);
  await cdp.send("Page.enable");
  await cdp.send("Runtime.enable");
  await cdp.send("Emulation.setDeviceMetricsOverride", {
    width: W, height: H, deviceScaleFactor: 1, mobile: false, screenWidth: W, screenHeight: H,
  });
  await cdp.send("Page.navigate", { url: HA_ORIGIN + "/" });
  await sleep(2000);
  const payload = JSON.stringify(TOKENS);
  await cdp.send("Page.addScriptToEvaluateOnNewDocument", {
    source: `try { localStorage.setItem("hassTokens", ${JSON.stringify(payload)}); } catch (e) {}`,
  });
  await cdp.eval(`localStorage.setItem("hassTokens", ${JSON.stringify(payload)}); 1`);
  await cdp.send("Page.navigate", { url: TARGET });
  await sleep(9000);

  const res = await cdp.eval(JS);
  res.forEach((r) => {
    const a = Object.keys(r.attrs || {}).length
      ? " " + JSON.stringify(r.attrs)
      : "";
    console.log(`${"  ".repeat(r.d)}${r.tag}${a}${r.txt ? "  «" + r.txt + "»" : ""}`);
  });

  ws.close();
  chrome.kill("SIGTERM");
  await sleep(300);
  fs.rmSync(profile, { recursive: true, force: true });
  process.exit(0);
})().catch(async (e) => {
  console.error("FAILED:", e.message);
  try { chrome.kill("SIGKILL"); } catch (x) {}
  process.exit(1);
});
