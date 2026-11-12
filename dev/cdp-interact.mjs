/**
 * 交互验证：点击设备卡片进入详情页 + 截图
 * 用法: node cdp-interact.mjs <列表页URL> <详情路径> <输出PNG> [宽] [高]
 */
import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const LIST_URL = process.argv[2] || "http://192.168.31.67:8123/device-cards";
const TARGET_NAME = process.argv[3] || "小厨宝";   // 要点击的设备名（模糊匹配）
const OUT = process.argv[4] || "/tmp/ha-detail.png";
const W = Number(process.argv[5] || 1440);
const H = Number(process.argv[6] || 1200);
const HA_ORIGIN = process.env.HA_ORIGIN || "http://192.168.31.67:8123";
const PORT = 9400 + Math.floor(Math.random() * 300);

const TOKENS = JSON.parse(fs.readFileSync("/tmp/ha_tokens.json", "utf8"));
TOKENS.expires = Date.now() + (TOKENS.expires_in || 1800) * 1000;

const CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const profile = fs.mkdtempSync(path.join(os.tmpdir(), "ha-cdp-"));
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
    if (r.exceptionDetails) throw new Error(JSON.stringify(r.exceptionDetails).slice(0, 400));
    return r.result.value;
  }
}

(async () => {
  const target = await getTarget();
  const ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((r) => ws.addEventListener("open", r, { once: true }));
  const cdp = new CDP(ws);
  await cdp.send("Page.enable");
  await cdp.send("Runtime.enable");

  // 注入 token
  await cdp.send("Page.navigate", { url: HA_ORIGIN + "/" });
  await sleep(2000);
  const payload = JSON.stringify(TOKENS);
  await cdp.send("Page.addScriptToEvaluateOnNewDocument", {
    source: `try { localStorage.setItem("hassTokens", ${JSON.stringify(payload)}); } catch (e) {}`,
  });
  await cdp.eval(`localStorage.setItem("hassTokens", ${JSON.stringify(payload)}); 1`);

  // 打开列表页
  await cdp.send("Page.navigate", { url: LIST_URL });
  await sleep(9000);

  // 找到目标设备卡片（按名称）—— HA 的卡片在 shadow DOM 里，需递归穿透
  const before = await cdp.eval(`(() => {
    const walk = (root, sel, out) => {
      let nodes; try { nodes = root.querySelectorAll("*"); } catch (e) { return out; }
      for (const el of nodes) {
        if (el.matches && el.matches(sel)) out.push(el);
        if (el.shadowRoot) walk(el.shadowRoot, sel, out);
      }
      return out;
    };
    window.__haWalk = walk;
    const cards = walk(document, "mi-device-card", []);
    return {
      url: location.href,
      total: cards.length,
      names: cards.map(c => c.shadowRoot?.querySelector(".mi-name")?.textContent?.trim()),
    };
  })()`);
  console.log("BEFORE:", JSON.stringify(before, null, 2));

  // 点击目标卡片
  await cdp.eval(`window.__targetName = ${JSON.stringify(TARGET_NAME)}; 1`);
  const clicked = await cdp.eval(`(() => {
    const cards = window.__haWalk(document, "mi-device-card", []);
    for (const c of cards) {
      const n = c.shadowRoot?.querySelector(".mi-name")?.textContent?.trim() || "";
      if (n.includes(window.__targetName)) {
        c.shadowRoot.querySelector(".mi-card").click();
        return {clicked: n};
      }
    }
    return {clicked: null};
  })()`);
  console.log("CLICK:", JSON.stringify(clicked));
  await sleep(6000);

  const after = await cdp.eval(`(() => {
    const walk = window.__haWalk;
    const d = walk(document, "mi-device-detail", [])[0];
    const r = d?.shadowRoot;
    let txt = "";
    if (r) txt = r.innerText || "";
    return {
      url: location.href,
      hasDetail: !!d,
      textLen: txt.length,
      text: txt.slice(0, 900),
      errCards: walk(document, "hui-error-card", []).length,
    };
  })()`);
  console.log("AFTER:", JSON.stringify(after, null, 2));

  const shot = await cdp.send("Page.captureScreenshot", { format: "png", captureBeyondViewport: true });
  fs.writeFileSync(OUT, Buffer.from(shot.data, "base64"));
  console.log("SHOT:", OUT, fs.statSync(OUT).size, "bytes");

  ws.close();
  chrome.kill("SIGTERM");
  await sleep(500);
  fs.rmSync(profile, { recursive: true, force: true });
  process.exit(0);
})().catch(async (e) => {
  console.error("FAILED:", e.message);
  try {
    chrome.kill("SIGKILL");
  } catch (x) {}
  process.exit(1);
});
