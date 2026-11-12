/**
 * 缓存场景验证：
 *   1) 先用无版本号 URL（用户浏览器旧缓存入口）加载一次页面
 *   2) 检查页面实际加载的 script src 是否带版本参数
 *   3) 读取该 JS 的 getGridOptions 内容，确认是否为新版 rows:"auto"
 *
 * 用法: node cdp-cache-check.mjs <面板URL> [宽] [高]
 */
import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const TARGET = process.argv[2] || "http://192.168.31.67:8123/device-cards";
const W = Number(process.argv[3] || 1440);
const H = Number(process.argv[4] || 1200);
const HA_ORIGIN = process.env.HA_ORIGIN || "http://192.168.31.67:8123";
const PORT = 9600 + Math.floor(Math.random() * 250);

const TOKENS = JSON.parse(fs.readFileSync("/tmp/ha_tokens.json", "utf8"));
TOKENS.expires = Date.now() + (TOKENS.expires_in || 1800) * 1000;

const CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const profile = fs.mkdtempSync(path.join(os.tmpdir(), "ha-cache-"));
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
    const r = await this.send("Runtime.evaluate", {
      expression,
      returnByValue: true,
      awaitPromise: true,
    });
    if (r.exceptionDetails) throw new Error(JSON.stringify(r.exceptionDetails).slice(0, 500));
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
  await cdp.send("Emulation.setDeviceMetricsOverride", {
    width: W, height: H, deviceScaleFactor: 1, mobile: W < 700, screenWidth: W, screenHeight: H,
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

  // 页面里实际加载的 mi-cards.js 脚本地址
  const res = await cdp.eval(`(() => {
    const scripts = [...document.querySelectorAll("script[src]")].map(s => s.getAttribute("src"));
    const miScript = scripts.find(s => s.includes("mi-cards.js"));
    // 已注册自定义元素的版本信息：直接看 getGridOptions 返回值
    const el = document.querySelector("mi-device-card");
    let gridOpts = null;
    if (el && typeof el.getGridOptions === "function") {
      try { gridOpts = el.getGridOptions(); } catch (e) { gridOpts = "ERR:" + e.message; }
    }
    // 卡片高度（判断是否被固定行高裁切）
    const r = el?.shadowRoot?.querySelector(".mi-card")?.getBoundingClientRect();
    return {
      miScriptUrl: miScript || null,
      gridOpts,
      cardH: r ? Math.round(r.height) : null,
      allScripts: scripts.filter(s => s.includes("mi-cards") || s.includes("resource")),
    };
  })()`);

  console.log(JSON.stringify(res, null, 2));

  const shot = await cdp.send("Page.captureScreenshot", { format: "png", captureBeyondViewport: true });
  fs.writeFileSync("/tmp/cache-check.png", Buffer.from(shot.data, "base64"));
  console.log("SHOT: /tmp/cache-check.png");

  ws.close();
  chrome.kill("SIGTERM");
  await sleep(400);
  fs.rmSync(profile, { recursive: true, force: true });
  process.exit(0);
})().catch(async (e) => {
  console.error("FAILED:", e.message);
  try { chrome.kill("SIGKILL"); } catch (x) {}
  process.exit(1);
});
