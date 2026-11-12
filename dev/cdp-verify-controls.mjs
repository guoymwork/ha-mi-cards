/**
 * 控件联通性验证（零副作用）：拦截 hass.callService，只记录将要发出的服务调用，
 * 不真正下发到设备。用于验证卡片开关 / 档位 / 常用功能的服务接线是否正确。
 *
 * 用法: node cdp-verify-controls.mjs
 */
import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const HA_ORIGIN = "http://ha.local:8123";
const DETAIL_URL =
  HA_ORIGIN +
  "/device-cards/" +
  encodeURIComponent("米家智能小厨宝7l-s1");
const PORT = 9700 + Math.floor(Math.random() * 200);

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
    "--window-size=1440,1100",
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
  send(method, params) {
    const id = ++this.id;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.ws.send(JSON.stringify({ id, method, params: params || {} }));
    });
  }
  async eval(expr) {
    const r = await this.send("Runtime.evaluate", {
      expression: expr,
      awaitPromise: true,
      returnByValue: true,
    });
    if (r.exceptionDetails) throw new Error(r.exceptionDetails.text + " " + JSON.stringify(r.exceptionDetails.exception || {}));
    return r.result.value;
  }
}

const WALK = `
  const walk = (root, sel, out) => {
    let n; try { n = root.querySelectorAll("*"); } catch (e) { return out; }
    for (const el of n) { if (el.matches && el.matches(sel)) out.push(el); if (el.shadowRoot) walk(el.shadowRoot, sel, out); }
    return out;
  };`;

(async () => {
  const list = await getTarget();
  const ws = new WebSocket(list.webSocketDebuggerUrl);
  await new Promise((res) => ws.addEventListener("open", res));
  const cdp = new CDP(ws);

  await cdp.send("Page.enable");
  await cdp.send("Runtime.enable");
  await cdp.send("Page.addScriptToEvaluateOnNewDocument", {
    source: `try { localStorage.setItem("hassTokens", ${JSON.stringify(JSON.stringify(TOKENS))}); } catch (e) {}`,
  });
  await cdp.send("Page.navigate", { url: HA_ORIGIN + "/" });
  await sleep(2500);
  await cdp.eval(`localStorage.setItem("hassTokens", ${JSON.stringify(JSON.stringify(TOKENS))}); 1`);
  await cdp.send("Page.navigate", { url: DETAIL_URL });
  await sleep(9000);

  const result = await cdp.eval(`(() => {
    ${WALK}
    const d = walk(document, "mi-device-detail", [])[0];
    if (!d) return JSON.stringify({ err: "详情卡片未挂载" });
    const sr = d.shadowRoot;
    const hass = d._hass;
    const calls = [];
    const orig = hass.callService.bind(hass);
    hass.callService = (domain, service, data, target) => {
      calls.push({ domain, service, data });
      return Promise.resolve();
    };

    const segs = [...sr.querySelectorAll(".mi-seg-btn")];
    const segLabels = segs.map(b => b.textContent.trim());
    if (segs[1]) segs[1].click();                       // 档位：中温

    const sw = sr.querySelector("[data-toggle]");       // 常用功能开关（防冻提醒）
    const swText = sw ? sw.closest(".mi-row").textContent.trim().slice(0, 12) : null;
    if (sw) sw.click();

    const ns = sr.querySelector("[data-number-switch]"); // 一键杀菌（number 当开关用）
    const nsText = ns ? ns.closest(".mi-row").textContent.trim().slice(0, 12) : null;
    if (ns) ns.click();

    const power = sr.querySelector('[data-role="power"]');
    if (power) power.click();

    hass.callService = orig;
    return JSON.stringify({
      segLabels,
      swText, nsText,
      calls,
    });
  })()`);

  console.log("CONTROL-CHECK:", result);

  // 列表页：卡片右上角开关
  await cdp.send("Page.navigate", { url: HA_ORIGIN + "/device-cards" });
  await sleep(9000);
  const listResult = await cdp.eval(`(() => {
    ${WALK}
    const cards = walk(document, "mi-device-card", []);
    if (!cards.length) return JSON.stringify({ err: "无设备卡片" });
    const c = cards.find(x => x.shadowRoot && x.shadowRoot.querySelector(".mi-switch")) || cards[0];
    const hass = c._hass;
    const calls = [];
    const orig = hass.callService.bind(hass);
    hass.callService = (domain, service, data) => { calls.push({ domain, service, data }); return Promise.resolve(); };
    const name = c.shadowRoot.querySelector(".mi-name").textContent.trim();
    const sw = c.shadowRoot.querySelector(".mi-switch");
    if (sw) sw.click();
    hass.callService = orig;
    return JSON.stringify({ card: name, hasSwitch: !!sw, switchCls: sw ? sw.className : null, calls });
  })()`);
  console.log("LIST-SWITCH-CHECK:", listResult);

  ws.close();
  chrome.kill("SIGTERM");
  await sleep(500);
  fs.rmSync(profile, { recursive: true, force: true });
  process.exit(0);
})().catch((e) => {
  console.error("FAILED:", e.message);
  try { chrome.kill("SIGKILL"); } catch (x) {}
  process.exit(1);
});
