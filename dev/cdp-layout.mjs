/**
 * 布局体检：量卡片包围盒 -> 两两判重叠 -> 输出越界/重叠报告
 * 用法: node cdp-layout.mjs <列表页URL> [宽] [高] [输出JSON]
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
const PORT = 9700 + Math.floor(Math.random() * 250);

const TOKENS = JSON.parse(fs.readFileSync("/tmp/ha_tokens.json", "utf8"));
TOKENS.expires = Date.now() + (TOKENS.expires_in || 1800) * 1000;

const CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const profile = fs.mkdtempSync(path.join(os.tmpdir(), "ha-layout-"));
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

const LAYOUT_JS = `(() => {
  const walk = (root, sel, out) => {
    let nodes; try { nodes = root.querySelectorAll("*"); } catch (e) { return out; }
    for (const el of nodes) {
      if (el.matches && el.matches(sel)) out.push(el);
      if (el.shadowRoot) walk(el.shadowRoot, sel, out);
    }
    return out;
  };
  const cards = walk(document, "mi-device-card", []);
  const items = cards.map((c, i) => {
    const el = c.shadowRoot?.querySelector(".mi-card") || c;
    const r = el.getBoundingClientRect();
    return {
      i,
      name: c.shadowRoot?.querySelector(".mi-name")?.textContent?.trim() || ("#" + i),
      x: Math.round(r.x), y: Math.round(r.y),
      w: Math.round(r.width), h: Math.round(r.height),
      bottom: Math.round(r.bottom), right: Math.round(r.right),
    };
  });
  // 两两重叠判定（面积交集 > 4px^2 视为叠压）
  const overlaps = [];
  for (let a = 0; a < items.length; a++) {
    for (let b = a + 1; b < items.length; b++) {
      const A = items[a], B = items[b];
      const ox = Math.min(A.right, B.right) - Math.max(A.x, B.x);
      const oy = Math.min(A.bottom, B.bottom) - Math.max(A.y, B.y);
      if (ox > 4 && oy > 4) {
        overlaps.push({ a: A.name, b: B.name, ox: Math.round(ox), oy: Math.round(oy) });
      }
    }
  }
  // 找出 grid 容器的 CSS（行高是固定值就会叠压）
  const gridInfo = [];
  walk(document, "hui-card, ha-card, hui-grid-card, hui-section", []);
  const sec = document.querySelectorAll("hui-sections-view, hui-section-grid, hui-grid-card");
  for (const s of sec) {
    const cs = getComputedStyle(s);
    gridInfo.push({
      tag: s.tagName.toLowerCase() + (s.className ? "." + String(s.className).split(" ").filter(Boolean).join(".") : ""),
      display: cs.display,
      gridTemplateRows: cs.gridTemplateRows,
      gridAutoRows: cs.gridAutoRows,
      gridTemplateColumns: cs.gridTemplateColumns,
      height: Math.round(s.getBoundingClientRect().height),
    });
  }
  // 卡片内部是否溢出（内容高度 > 卡片高度）
  const overflow = [];
  for (const c of cards) {
    const el = c.shadowRoot?.querySelector(".mi-card");
    if (!el) continue;
    const cr = el.getBoundingClientRect();
    const inner = c.shadowRoot?.querySelector(".mi-body") || c.shadowRoot;
    if (inner) {
      const need = inner.scrollHeight;
      if (need > cr.height + 2) {
        overflow.push({
          name: c.shadowRoot?.querySelector(".mi-name")?.textContent?.trim(),
          cardH: Math.round(cr.height), needH: need,
        });
      }
    }
  }
  return {
    url: location.href,
    vw: innerWidth, vh: innerHeight,
    count: items.length,
    items,
    overlaps,
    overflow,
    gridInfo,
    docH: document.documentElement.scrollHeight,
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
    width: W,
    height: H,
    deviceScaleFactor: 1,
    mobile: W < 700,
    screenWidth: W,
    screenHeight: H,
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

  // 触发懒加载（滚动到底再回来），确保所有卡片都渲染
  await cdp.eval(`window.scrollTo(0, document.body.scrollHeight); 1`);
  await sleep(2500);
  await cdp.eval(`window.scrollTo(0, 0); 1`);
  await sleep(1500);

  const res = await cdp.eval(LAYOUT_JS);
  const summary = {
    vw: res.vw,
    count: res.count,
    overlapCount: res.overlaps.length,
    overlaps: res.overlaps.slice(0, 20),
    overflow: res.overflow.slice(0, 20),
    gridInfo: res.gridInfo,
    docH: res.docH,
  };
  console.log("SUMMARY:", JSON.stringify(summary, null, 2));
  console.log("ITEMS:", JSON.stringify(res.items));
  if (OUTJSON) {
    fs.writeFileSync(OUTJSON, JSON.stringify(res, null, 2));
    console.log("JSON:", OUTJSON);
  }

  ws.close();
  chrome.kill("SIGTERM");
  await sleep(400);
  fs.rmSync(profile, { recursive: true, force: true });
  process.exit(0);
})().catch(async (e) => {
  console.error("FAILED:", e.message);
  try {
    chrome.kill("SIGKILL");
  } catch (x) {}
  process.exit(1);
});
