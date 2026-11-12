/**
 * 卡片细节探针：量 host/.mi-card 盒子、按钮图标、区域行、顶部二级菜单
 * 用法: node cdp-probe.mjs <列表页URL> [宽] [高]
 */
import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const TARGET = process.argv[2] || "http://192.168.31.67:8123/device-cards";
const W = Number(process.argv[3] || 1440);
const H = Number(process.argv[4] || 1200);
const HA_ORIGIN = process.env.HA_ORIGIN || "http://192.168.31.67:8123";
const PORT = 9800 + Math.floor(Math.random() * 150);

const TOKENS = JSON.parse(fs.readFileSync("/tmp/ha_tokens.json", "utf8"));
TOKENS.expires = Date.now() + (TOKENS.expires_in || 1800) * 1000;

const CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const profile = fs.mkdtempSync(path.join(os.tmpdir(), "ha-probe-"));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const chrome = spawn(CHROME, [
  "--headless=new", `--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`,
  "--no-first-run", "--no-default-browser-check", "--disable-gpu",
  "--no-sandbox", "--disable-dev-shm-usage", "--hide-scrollbars",
  "--proxy-server=http://127.0.0.1:7897", "--proxy-bypass-list=<-loopback>",
  `--window-size=${W},${H}`, "about:blank",
], { stdio: "ignore", env: { ...process.env, http_proxy: "", https_proxy: "", HTTP_PROXY: "", HTTPS_PROXY: "" } });

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
  async eval(expression) {
    const r = await this.send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
    if (r.exceptionDetails) throw new Error(JSON.stringify(r.exceptionDetails).slice(0, 800));
    return r.result.value;
  }
}

const PROBE_JS = `(() => {
  const walk = (root, sel, out) => {
    let nodes; try { nodes = root.querySelectorAll("*"); } catch (e) { return out; }
    for (const el of nodes) {
      if (el.matches && el.matches(sel)) out.push(el);
      if (el.shadowRoot) walk(el.shadowRoot, sel, out);
    }
    return out;
  };
  const hosts = walk(document, "mi-device-card", []);
  const cards = hosts.slice(0, 8).map((h) => {
    const hb = h.getBoundingClientRect();
    const inner = h.shadowRoot?.querySelector(".mi-card");
    const ib = inner ? inner.getBoundingClientRect() : null;
    const cs = getComputedStyle(h);
    const btn = h.shadowRoot?.querySelector(".mi-btn");
    const btnBox = btn ? btn.getBoundingClientRect() : null;
    const iconEl = btn?.querySelector("ha-icon");
    const iconBox = iconEl ? iconEl.getBoundingClientRect() : null;
    const areaEl = h.shadowRoot?.querySelector(".mi-area");
    return {
      name: h.shadowRoot?.querySelector(".mi-name")?.textContent?.trim() || "",
      sub: (h.shadowRoot?.querySelector(".mi-sub")?.textContent || "").trim(),
      area: areaEl ? areaEl.textContent : null,
      hostW: +hb.width.toFixed(1), hostH: +hb.height.toFixed(1),
      hostRatio: +(hb.width / hb.height).toFixed(4),
      innerW: ib ? +ib.width.toFixed(1) : null, innerH: ib ? +ib.height.toFixed(1) : null,
      aspect: cs.aspectRatio, cssH: cs.height, cssW: cs.width,
      btnIcon: iconEl?.getAttribute("icon") || null,
      btnW: btnBox ? +btnBox.width.toFixed(1) : null,
      btnH: btnBox ? +btnBox.height.toFixed(1) : null,
      btnRadius: btn ? getComputedStyle(btn).borderRadius : null,
      btnBg: btn ? getComputedStyle(btn).backgroundColor : null,
      iconRendered: iconBox ? +(iconBox.width).toFixed(1) : null,
      hasBtn: !!btn,
    };
  });
  // 顶部二级菜单（HA 原生 view tab 栏）
  const walkTabs = (root, out) => {
    let nodes; try { nodes = root.querySelectorAll("*"); } catch (e) { return out; }
    for (const el of nodes) {
      const tag = el.tagName.toLowerCase();
      if (tag === "ha-tab" || tag === "paper-tab" || tag === "mwc-tab" || el.getAttribute("role") === "tab") {
        out.push({
          tag,
          text: (el.textContent || "").trim().slice(0, 30),
          icon: el.querySelector("ha-icon")?.getAttribute("icon") || "",
          selected: el.getAttribute("selected") !== null || el.getAttribute("aria-selected") === "true",
        });
      }
      if (el.shadowRoot) walkTabs(el.shadowRoot, out);
    }
    return out;
  };
  const tabs = walkTabs(document, []);
  const scripts = [...document.querySelectorAll("script[src]")].map((s) => s.src).filter((s) => s.includes("mi-cards"));
  const styleTag = hosts[0]?.shadowRoot?.querySelector("style")?.textContent || "";
  return {
    url: location.href,
    count: hosts.length,
    cards,
    tabs,
    scripts,
    cssHasAspect: styleTag.includes("aspect-ratio"),
    cssHasBtn: styleTag.includes(".mi-btn"),
    cssHasSub: styleTag.includes(".mi-sub"),
    gridCols: (() => {
      const g = document.querySelector("mi-area-wall")?.shadowRoot?.querySelector(".mi-grid");
      return g ? getComputedStyle(g).gridTemplateColumns : null;
    })(),
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
  const out = await cdp.eval(PROBE_JS);
  console.log(JSON.stringify(out, null, 1));
  ws.close(); chrome.kill(); process.exit(0);
})().catch((e) => { console.error("ERR", e.message); chrome.kill(); process.exit(1); });
