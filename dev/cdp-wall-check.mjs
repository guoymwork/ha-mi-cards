/**
 * 区域墙体检：递归穿透 shadow DOM，量标签栏/网格/卡片，检查叠压与占宽
 * 用法: node cdp-wall-check.mjs <URL> [宽] [高] [输出JSON]
 */
import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const TARGET = process.argv[2] || "http://ha.local:8123/device-cards";
const W = Number(process.argv[3] || 1440);
const H = Number(process.argv[4] || 1200);
const OUTJSON = process.argv[5] || "";
const HA_ORIGIN = process.env.HA_ORIGIN || "http://ha.local:8123";
const PORT = 9500 + Math.floor(Math.random() * 250);

const TOKENS = JSON.parse(fs.readFileSync("/tmp/ha_tokens.json", "utf8"));
TOKENS.expires = Date.now() + (TOKENS.expires_in || 1800) * 1000;

const CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const profile = fs.mkdtempSync(path.join(os.tmpdir(), "ha-wall-"));
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
    if (r.exceptionDetails) throw new Error(JSON.stringify(r.exceptionDetails).slice(0, 600));
    return r.result.value;
  }
}

const JS = `(() => {
  const walk = (root, sel, out) => {
    let nodes; try { nodes = root.querySelectorAll("*"); } catch (e) { return out; }
    for (const el of nodes) {
      if (el.matches && el.matches(sel)) out.push(el);
      if (el.shadowRoot) walk(el.shadowRoot, sel, out);
    }
    return out;
  };
  const wall = walk(document, "mi-area-wall", [])[0];
  if (!wall) return { found: false, url: location.href, body: document.body.innerText.slice(0, 300) };
  const r = wall.shadowRoot;
  const grid = r.querySelector(".mi-grid");
  const tabs = [...r.querySelectorAll(".mi-tab")];
  const cards = [...r.querySelectorAll("mi-device-card")];
  const gcs = grid ? getComputedStyle(grid) : null;
  const wallRect = wall.getBoundingClientRect();

  // 可见卡片（未被标签过滤隐藏）
  const vis = cards.filter(c => c.style.display !== "none");
  const items = vis.map((c, i) => {
    const el = c.shadowRoot?.querySelector(".mi-card");
    const b = el ? el.getBoundingClientRect() : c.getBoundingClientRect();
    const nm = c.shadowRoot?.querySelector(".mi-name");
    return {
      i,
      name: nm?.textContent?.trim(),
      x: Math.round(b.x), y: Math.round(b.y),
      w: Math.round(b.width), h: Math.round(b.height),
      bottom: Math.round(b.bottom), right: Math.round(b.right),
      // 名字是否被截断（scrollWidth > clientWidth）
      truncated: nm ? nm.scrollWidth > nm.clientWidth + 1 : false,
    };
  });
  const overlaps = [];
  for (let a = 0; a < items.length; a++) {
    for (let b = a + 1; b < items.length; b++) {
      const A = items[a], B = items[b];
      const ox = Math.min(A.right, B.right) - Math.max(A.x, B.x);
      const oy = Math.min(A.bottom, B.bottom) - Math.max(A.y, B.y);
      if (ox > 4 && oy > 4) overlaps.push({ a: A.name, b: B.name, ox: Math.round(ox), oy: Math.round(oy) });
    }
  }
  // 每行卡片的行数分组（按 y）
  const rows = {};
  for (const it of items) { (rows[it.y] = rows[it.y] || []).push(it.name); }
  const rowInfo = Object.entries(rows).map(([y, ns]) => ({ y: Number(y), n: ns.length, names: ns }));

  return {
    found: true, url: location.href, vw: innerWidth,
    wallW: Math.round(wallRect.width), wallX: Math.round(wallRect.x),
    gridW: grid ? Math.round(grid.getBoundingClientRect().width) : null,
    cols: gcs ? gcs.gridTemplateColumns : null,
    gap: gcs ? gcs.gap : null,
    tabs: tabs.map(t => ({ txt: t.textContent.trim(), active: t.classList.contains("active") })),
    cardTotal: cards.length, cardVisible: vis.length,
    items, overlaps, overlapCount: overlaps.length,
    truncated: items.filter(i => i.truncated).map(i => i.name),
    rowInfo,
    heights: [...new Set(items.map(i => i.h))],
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
  const png = OUTJSON ? OUTJSON.replace(/\.json$/, ".png") : "/tmp/wall-check.png";
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
