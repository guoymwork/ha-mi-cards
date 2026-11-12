/**
 * 图片体检：递归穿透 shadow DOM，检查每张卡片的图片 src / 加载状态 / 自然尺寸
 * 用法: node cdp-img-check.mjs <URL> [宽] [高] [名称关键字] [输出JSON]
 */
import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const TARGET = process.argv[2] || "http://ha.local:8123/device-cards";
const W = Number(process.argv[3] || 1440);
const H = Number(process.argv[4] || 1200);
const KEYWORD = process.argv[5] || "";
const OUTJSON = process.argv[6] || "";
const HA_ORIGIN = process.env.HA_ORIGIN || "http://ha.local:8123";
const PORT = 9800 + Math.floor(Math.random() * 150);

const TOKENS = JSON.parse(fs.readFileSync("/tmp/ha_tokens.json", "utf8"));
TOKENS.expires = Date.now() + (TOKENS.expires_in || 1800) * 1000;

const CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const profile = fs.mkdtempSync(path.join(os.tmpdir(), "ha-img-"));
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
    if (r.exceptionDetails) throw new Error(JSON.stringify(r.exceptionDetails).slice(0, 600));
    return r.result.value;
  }
}

const JS = `(() => {
  const kw = ${JSON.stringify(KEYWORD)};
  const walk = (root, sel, out) => {
    let nodes; try { nodes = root.querySelectorAll("*"); } catch (e) { return out; }
    for (const el of nodes) {
      if (el.matches && el.matches(sel)) out.push(el);
      if (el.shadowRoot) walk(el.shadowRoot, sel, out);
    }
    return out;
  };
  const cards = walk(document, "mi-device-card, mi-device-detail", []);
  const all = [];
  for (const c of cards) {
    const nm = c.shadowRoot?.querySelector(".mi-name");
    const name = (nm?.textContent?.trim()) || c.getAttribute("name") || "";
    const img = c.shadowRoot?.querySelector("img");
    const r = c.getBoundingClientRect();
    all.push({
      tag: c.tagName, name,
      src: img ? img.getAttribute("src") : null,
      hasImg: !!img,
      complete: img ? img.complete : null,
      natW: img ? img.naturalWidth : null,
      natH: img ? img.naturalHeight : null,
      renderedW: img ? Math.round(img.getBoundingClientRect().width) : null,
      renderedH: img ? Math.round(img.getBoundingClientRect().height) : null,
      cardW: Math.round(r.width), cardH: Math.round(r.height),
      x: Math.round(r.x), y: Math.round(r.y),
    });
  }
  const matched = kw ? all.filter(i => i.name.includes(kw)) : all;
  const broken = matched.filter(i => i.hasImg && (!i.complete || !i.natW));
  const noImg = matched.filter(i => !i.hasImg);
  const sizes = [...new Set(matched.filter(i => i.natW).map(i => i.natW + "x" + i.natH))];
  return {
    total: all.length, matched: matched.length,
    brokenCount: broken.length, broken,
    noImgCount: noImg.length, noImg: noImg.map(i => i.name),
    sizes, items: matched,
  };
})()`;

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
  await sleep(10000);
  await cdp.eval(`window.scrollTo(0, document.body.scrollHeight); 1`);
  await sleep(2500);
  await cdp.eval(`window.scrollTo(0, 0); 1`);
  await sleep(1500);

  const res = await cdp.eval(JS);
  console.log(JSON.stringify(res, null, 2));
  if (OUTJSON) fs.writeFileSync(OUTJSON, JSON.stringify(res, null, 2));

  const shot = await cdp.send("Page.captureScreenshot", { format: "png", captureBeyondViewport: true });
  const png = OUTJSON ? OUTJSON.replace(/\.json$/, ".png") : "/tmp/img-check.png";
  fs.writeFileSync(png, Buffer.from(shot.data, "base64"));
  console.log("SHOT:", png);

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
