/**
 * 截取侧边栏区域截图（裁剪左侧 320px），用于观察二级菜单结构
 * 用法: node cdp-sidebar-shot.mjs <URL> [宽] [高] [输出PNG]
 */
import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const TARGET = process.argv[2] || "http://192.168.31.67:8123/zz-nav-test";
const W = Number(process.argv[3] || 1440);
const H = Number(process.argv[4] || 1200);
const OUT = process.argv[5] || "/tmp/sidebar.png";
const HA_ORIGIN = process.env.HA_ORIGIN || "http://192.168.31.67:8123";
const PORT = 9950 + Math.floor(Math.random() * 40);

const TOKENS = JSON.parse(fs.readFileSync("/tmp/ha_tokens.json", "utf8"));
TOKENS.expires = Date.now() + (TOKENS.expires_in || 1800) * 1000;

const CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const profile = fs.mkdtempSync(path.join(os.tmpdir(), "ha-shot-"));
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
  throw new Error("Chrome CDP not ready");
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
  const deep = (root, sel, max = 14) => {
    const found = [];
    const walk = (r, d) => {
      if (d > max) return;
      let nodes; try { nodes = r.querySelectorAll("*"); } catch (e) { return; }
      for (const el of nodes) {
        if (el.matches && el.matches(sel)) found.push(el);
        if (el.shadowRoot) walk(el.shadowRoot, d + 1);
      }
    };
    walk(root, 0);
    return found;
  };
  const lists = deep(document, "ha-list-nav");
  return lists.map(n => ({
    cls: String(n.className||""),
    text: (n.textContent||"").trim().replace(/\\s+/g," "),
    children: [...n.children].map(c => ({
      tag: c.tagName, cls: String(c.className||"").slice(0,60),
      text: (c.textContent||"").trim().replace(/\\s+/g," ").slice(0,50),
      attrs: [...c.attributes].map(a=>a.name+"="+a.value.slice(0,30)).join(","),
      sub: [...c.children].map(g=>({
        tag:g.tagName, text:(g.textContent||"").trim().replace(/\\s+/g," ").slice(0,40)
      })),
    })),
  }));
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
  console.log(JSON.stringify(res, null, 1));

  const shot = await cdp.send("Page.captureScreenshot", {
    format: "png",
    clip: { x: 0, y: 0, width: 330, height: Math.min(H, 900), scale: 1 },
  });
  fs.writeFileSync(OUT, Buffer.from(shot.data, "base64"));
  console.log("SHOT:", OUT);

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
