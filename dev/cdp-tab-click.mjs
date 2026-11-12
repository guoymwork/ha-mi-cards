/**
 * 区域标签栏交互验证：点击各区域标签 -> 检查可见卡片是否只剩该区域
 * 用法: node cdp-tab-click.mjs <URL> [宽] [高] [输出JSON]
 */
import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const TARGET = process.argv[2] || "http://192.168.31.67:8123/device-cards";
const W = Number(process.argv[3] || 1440);
const H = Number(process.argv[4] || 1200);
const OUTJSON = process.argv[5] || "";
const HA_ORIGIN = process.env.HA_ORIGIN || "http://192.168.31.67:8123";
const PORT = 9200 + Math.floor(Math.random() * 200);

const TOKENS = JSON.parse(fs.readFileSync("/tmp/ha_tokens.json", "utf8"));
TOKENS.expires = Date.now() + (TOKENS.expires_in || 1800) * 1000;

const CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const profile = fs.mkdtempSync(path.join(os.tmpdir(), "ha-tab-"));
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

const SETUP = `(() => {
  const walk = (root, sel, out) => {
    let nodes; try { nodes = root.querySelectorAll("*"); } catch (e) { return out; }
    for (const el of nodes) {
      if (el.matches && el.matches(sel)) out.push(el);
      if (el.shadowRoot) walk(el.shadowRoot, sel, out);
    }
    return out;
  };
  window.__walk = walk;
  const wall = walk(document, "mi-area-wall", [])[0];
  window.__wall = wall;
  window.__tabs = [...wall.shadowRoot.querySelectorAll(".mi-tab")];
  window.__visNames = () => [...wall.shadowRoot.querySelectorAll("mi-device-card")]
    .filter(c => c.style.display !== "none")
    .map(c => ({
      name: c.shadowRoot?.querySelector(".mi-name")?.textContent?.trim(),
      group: c.dataset.group,
    }));
  return { tabs: window.__tabs.map(t => ({ area: t.dataset.area, txt: t.textContent.trim() })) };
})()`;

const CLICK = `(() => {
  const idx = window.__clickIdx;
  const btn = window.__tabs[idx];
  if (!btn) return {clicked: null};
  btn.click();
  return {
    clicked: btn.dataset.area,
    active: [...window.__tabs].filter(t => t.classList.contains("active")).map(t => t.dataset.area),
    visible: window.__visNames().length,
    visibleNames: window.__visNames().map(v => v.name),
    groups: [...new Set(window.__visNames().map(v => v.group))],
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

  const setup = await cdp.eval(SETUP);
  console.log("TABS:", JSON.stringify(setup.tabs));

  const results = [];
  for (let i = 0; i < setup.tabs.length; i++) {
    await cdp.eval(`window.__clickIdx = ${i}; 1`);
    const r = await cdp.eval(CLICK);
    await sleep(700);
    const res = { idx: i, ...r };
    results.push(res);
    console.log(
      `点击[${r.clicked}] -> 可见 ${r.visible} 张 | 分组 ${JSON.stringify(r.groups)} | 全部同组: ${
        r.groups && r.groups.length === 1 ? "是" : "否"
      }`
    );
  }

  // 回到全屋
  await cdp.eval(`window.__clickIdx = 0; 1`);
  await cdp.eval(CLICK);
  await sleep(800);

  const shot = await cdp.send("Page.captureScreenshot", { format: "png", captureBeyondViewport: true });
  const png = OUTJSON ? OUTJSON.replace(/\.json$/, ".png") : "/tmp/tab-click.png";
  fs.writeFileSync(png, Buffer.from(shot.data, "base64"));
  console.log("SHOT:", png);
  if (OUTJSON) fs.writeFileSync(OUTJSON, JSON.stringify(results, null, 2));

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
