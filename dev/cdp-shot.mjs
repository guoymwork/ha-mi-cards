/**
 * 无头 Chrome 验证脚本（Node 22 + CDP，无第三方依赖）
 * 用法: node cdp-shot.mjs <目标URL> <输出PNG> [宽] [高] [额外JS表达式]
 *
 * 认证要点（逆向 HA 2026.11 前端 core bundle 得到）：
 *   localStorage["hassTokens"] = {
 *     access_token, refresh_token, token_type,
 *     expires: <毫秒时间戳>,      // 前端判定 Date.now() > expires
 *     hassUrl: "<protocol>//<host>",   // 必须严格相等，无尾斜杠
 *     clientId: "<protocol>//<host>/"   // 默认带尾斜杠
 *   }
 *   另需绕过系统代理（HTTP_PROXY 会把内网请求交给 Clash 导致 502）
 */
import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const TARGET = process.argv[2] || "http://192.168.31.67:8123/";
const OUT = process.argv[3] || "/tmp/ha-shot.png";
const W = Number(process.argv[4] || 1440);
const H = Number(process.argv[5] || 1200);
const EXTRA_JS = process.argv[6] || "null";
const HA_ORIGIN = process.env.HA_ORIGIN || "http://192.168.31.67:8123";
const PORT = 9333 + Math.floor(Math.random() * 300);

const TOKENS = JSON.parse(fs.readFileSync("/tmp/ha_tokens.json", "utf8"));
// 本地运行时刷新有效期，避免过期
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
    // 本机直连局域网被沙箱阻断（ERR_ADDRESS_UNREACHABLE），必须走 Clash 代理
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
    } catch (e) {
      /* retry */
    }
    await sleep(250);
  }
  throw new Error("Chrome CDP 未就绪");
}

class CDP {
  constructor(ws) {
    this.ws = ws;
    this.id = 0;
    this.pending = new Map();
    this.events = [];
    ws.addEventListener("message", (ev) => {
      const m = JSON.parse(ev.data);
      if (m.id && this.pending.has(m.id)) {
        const { resolve, reject } = this.pending.get(m.id);
        this.pending.delete(m.id);
        m.error ? reject(new Error(JSON.stringify(m.error))) : resolve(m.result);
      } else if (m.method) {
        this.events.push(m);
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
    if (r.exceptionDetails) throw new Error(JSON.stringify(r.exceptionDetails).slice(0, 400));
    return r.result.value;
  }
}

const DIAG_JS = `(() => {
  const errs = document.querySelectorAll("hui-error-card, hui-card-error").length;
  const tiles = document.querySelectorAll("hui-tile-card").length;
  const custom = document.querySelectorAll("mi-device-card, mi-device-detail").length;
  const shadows = [...document.querySelectorAll("mi-device-card")].map(e => {
    const r = e.shadowRoot;
    return r ? {
      name: r.querySelector(".mi-name")?.textContent?.trim(),
      hasImg: !!r.querySelector("img"),
      imgOk: r.querySelector("img")?.complete && r.querySelector("img")?.naturalWidth > 0,
      switchOn: !!r.querySelector(".mi-switch.on"),
      hasSwitch: !!r.querySelector(".mi-switch"),
    } : null;
  });
  return {
    url: location.href,
    title: document.title,
    errorCards: errs,
    tileCards: tiles,
    customCards: custom,
    customNames: shadows,
    bodyText: document.body.innerText.slice(0, 400),
  };
})()`;

(async () => {
  const target = await getTarget();
  const ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((r) => ws.addEventListener("open", r, { once: true }));
  const cdp = new CDP(ws);

  await cdp.send("Page.enable");
  await cdp.send("Runtime.enable");

  // 移动端模拟：必须用 CDP 设备指标覆盖，--window-size 只改窗口大小，
  // 页面视口仍按桌面计算（HA 前端会因 meta viewport 变成 500px）
  if (process.env.MOBILE === "1") {
    await cdp.send("Emulation.setDeviceMetricsOverride", {
      width: W,
      height: H,
      deviceScaleFactor: 2,
      mobile: true,
      screenWidth: W,
      screenHeight: H,
    });
    await cdp.send("Emulation.setTouchEmulationEnabled", { enabled: true });
    console.log("mobile emulation:", W, "x", H);
  }

  // 1) 先打开同源页面，让 localStorage 有正确的 origin
  await cdp.send("Page.navigate", { url: HA_ORIGIN + "/" });
  await sleep(2000);

  // 2) 注入正确格式的 hassTokens
  const payload = JSON.stringify(TOKENS);
  const injectSrc = `try { localStorage.setItem("hassTokens", ${JSON.stringify(payload)}); } catch (e) {}`;
  await cdp.send("Page.addScriptToEvaluateOnNewDocument", { source: injectSrc });
  const injected = await cdp.eval(
    `(() => { try { localStorage.setItem("hassTokens", ${JSON.stringify(payload)}); const o=JSON.parse(localStorage.getItem("hassTokens")); return {ok:true, expires:o.expires, hassUrl:o.hassUrl}; } catch(e) { return {ok:false, err:e.message}; } })()`
  );
  console.log("inject:", JSON.stringify(injected));

  // 3) 打开目标页
  await cdp.send("Page.navigate", { url: TARGET });
  await sleep(9000);

  // 4) 诊断
  const diag = await cdp.eval(DIAG_JS);
  console.log("DIAG:", JSON.stringify(diag, null, 2));

  if (EXTRA_JS && EXTRA_JS !== "null") {
    try {
      const extra = await cdp.eval(EXTRA_JS);
      console.log("EXTRA:", JSON.stringify(extra, null, 2));
    } catch (e) {
      console.log("EXTRA_ERR:", e.message);
    }
  }

  // 5) 截图
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
