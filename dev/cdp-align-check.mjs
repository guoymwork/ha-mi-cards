// 卡片整齐度体检：检查所有卡片的位置/尺寸是否完全一致（无参差、无重叠）
// 用法: node cdp-align-check.mjs <url> [width] [height]
import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const URL_ = process.argv[2] || "http://ha.local:8123/device-cards";
const W = Number(process.argv[3] || 1440);
const H = Number(process.argv[4] || 1200);
const HA_ORIGIN = process.env.HA_ORIGIN || "http://ha.local:8123";
const CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const PORT = 9900 + Math.floor(Math.random() * 120);
const profile = fs.mkdtempSync(path.join(os.tmpdir(), "align-"));

const TOKENS = JSON.parse(fs.readFileSync("/tmp/ha_tokens.json", "utf8"));
TOKENS.expires = Date.now() + (TOKENS.expires_in || 1800) * 1000;

const chrome = spawn(CHROME, [
  "--headless=new", `--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`,
  "--no-first-run", "--no-default-browser-check", "--disable-gpu",
  "--no-sandbox", "--disable-dev-shm-usage", "--hide-scrollbars",
  "--proxy-server=http://127.0.0.1:7897", "--proxy-bypass-list=<-loopback>",
  `--window-size=${W},${H}`, "about:blank",
], { stdio: "ignore", env: { ...process.env, http_proxy: "", https_proxy: "", HTTP_PROXY: "", HTTPS_PROXY: "" } });

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function cdpTargets() {
  for (let i = 0; i < 80; i++) {
    try {
      const r = await fetch(`http://127.0.0.1:${PORT}/json/list`);
      const j = await r.json();
      const page = j.find((t) => t.type === "page");
      if (page) return page;
    } catch {}
    await sleep(250);
  }
  throw new Error("chrome not ready");
}

class CDP {
  constructor(ws) {
    this.ws = ws; this.id = 0; this.pending = new Map();
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
        if (this.pending.has(id)) { this.pending.delete(id); reject(new Error("timeout " + method)); }
      }, 45000);
    });
  }
}

const target = await cdpTargets();
const ws = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((res, rej) => {
  ws.addEventListener("open", res);
  ws.addEventListener("error", rej);
});
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
await cdp.send("Runtime.evaluate", { expression: `localStorage.setItem("hassTokens", ${JSON.stringify(payload)}); 1` });
await cdp.send("Page.navigate", { url: URL_ });
await sleep(9000);
await cdp.send("Runtime.evaluate", { expression: `
  document.querySelectorAll('ha-dialog, ha-alert, .backdrop').forEach(e=>e.remove());
  window.scrollTo(0, document.body.scrollHeight); true` });
await sleep(2500);
await cdp.send("Runtime.evaluate", { expression: "window.scrollTo(0,0); true" });
await sleep(1200);

const expr = `(() => {
  const walk = (root, sel, out) => {
    let nodes; try { nodes = root.querySelectorAll("*"); } catch (e) { return out; }
    for (const el of nodes) {
      if (el.matches && el.matches(sel)) out.push(el);
      if (el.shadowRoot) walk(el.shadowRoot, sel, out);
    }
    return out;
  };
  const cards = walk(document, "mi-device-card", []);
  const items = cards.map((c) => {
    const r = c.getBoundingClientRect();
    const inner = c.shadowRoot.querySelector('.mi-card');
    const ir = inner ? inner.getBoundingClientRect() : null;
    const name = c.shadowRoot.querySelector('.mi-name');
    const sub = c.shadowRoot.querySelector('.mi-sub');
    const img = c.shadowRoot.querySelector('.mi-media img');
    const btn = c.shadowRoot.querySelector('.mi-btn');
    const br = btn ? btn.getBoundingClientRect() : null;
    const mr = img ? img.getBoundingClientRect() : null;
    return {
      name: name ? name.textContent.trim() : '',
      x: +r.x.toFixed(2), y: +r.y.toFixed(2), w: +r.width.toFixed(2), h: +r.height.toFixed(2),
      innerH: ir ? +ir.height.toFixed(2) : null,
      innerW: ir ? +ir.width.toFixed(2) : null,
      nameH: name ? +name.getBoundingClientRect().height.toFixed(2) : null,
      subH: sub ? +sub.getBoundingClientRect().height.toFixed(2) : null,
      imgW: mr ? +mr.width.toFixed(2) : null,
      imgH: mr ? +mr.height.toFixed(2) : null,
      btnSize: br ? +br.width.toFixed(2) : null,
      btnX: br ? +br.x.toFixed(2) : null,
      btnY: br ? +br.y.toFixed(2) : null,
    };
  });
  return { count: items.length, items };
})()`;

const r = await cdp.send("Runtime.evaluate", { expression: expr, returnByValue: true, awaitPromise: true });
const data = r?.result?.value;
if (!data || data.error) {
  console.log("ERR", JSON.stringify(r).slice(0, 600));
} else {
  const it = data.items;
  const uniq = (k) => [...new Set(it.map((x) => x[k]))];
  console.log(`视口 ${W}x${H} | 卡片 ${it.length} 张`);
  console.log("宽度集合:", uniq("w"), "| 高度集合:", uniq("h"));
  console.log("内部 .mi-card 高度集合:", uniq("innerH"));
  console.log("名称行高集合:", uniq("nameH"), "| 状态行高集合:", uniq("subH"));
  console.log("按钮尺寸集合:", uniq("btnSize"));
  console.log("图片宽度集合:", uniq("imgW"));

  // 逐行检查 y 对齐
  const rows = {};
  it.forEach((c) => { (rows[c.y] = rows[c.y] || []).push(c); });
  const rowYs = Object.keys(rows).map(Number).sort((a, b) => a - b);
  let ragged = 0;
  for (const y of rowYs) {
    const hs = new Set(rows[y].map((c) => c.h));
    if (hs.size > 1) { ragged++; console.log("  !! 行 y=" + y + " 高度不一致:", [...hs]); }
  }
  // 重叠检测
  let overlap = 0;
  for (let i = 0; i < it.length; i++) {
    for (let j = i + 1; j < it.length; j++) {
      const a = it[i], b = it[j];
      const ox = Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x);
      const oy = Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y);
      if (ox > 1 && oy > 1) { overlap++; console.log(`  !! 重叠: ${a.name} x ${b.name}`); }
    }
  }
  // 文字溢出检测
  const overflow = it.filter((c) => c.nameH > 40 || c.subH > 40);
  console.log(`\n结果: 行高不一致 ${ragged} 行 | 卡片重叠 ${overlap} 处 | 文字行异常 ${overflow.length} 处`);
  console.log(`结论: ${ragged === 0 && overlap === 0 && overflow.length === 0 ? "✅ 完全整齐" : "❌ 存在参差"}`);
  // 抽样打印
  it.slice(0, 5).forEach((c) => console.log(" ", c.name, c.x, c.y, c.w + "x" + c.h, "图", c.imgW + "x" + c.imgH, "钮", c.btnSize));
}

ws.close();
chrome.kill();
fs.rmSync(profile, { recursive: true, force: true });
process.exit(0);
