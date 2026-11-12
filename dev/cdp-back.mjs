/**
 * 交互测试：详情页返回按钮 -> 是否回到所属区域视图
 * 用法: node cdp-back.mjs
 */
import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const HA_ORIGIN = "http://ha.local:8123";
const PORT = 9500 + Math.floor(Math.random() * 120);
const TOKENS = JSON.parse(fs.readFileSync("/tmp/ha_tokens.json", "utf8"));
TOKENS.expires = Date.now() + (TOKENS.expires_in || 1800) * 1000;

const CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const profile = fs.mkdtempSync(path.join(os.tmpdir(), "ha-back-"));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const chrome = spawn(CHROME, [
  "--headless=new", `--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`,
  "--no-first-run", "--no-default-browser-check", "--disable-gpu",
  "--no-sandbox", "--disable-dev-shm-usage", "--hide-scrollbars",
  "--proxy-server=http://127.0.0.1:7897", "--proxy-bypass-list=<-loopback>",
  "--window-size=1200,1000", "about:blank",
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
      setTimeout(() => { if (this.pending.has(id)) { this.pending.delete(id); reject(new Error("timeout " + method)); } }, 45000);
    });
  }
  async eval(expression) {
    const r = await this.send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
    if (r.exceptionDetails) throw new Error(JSON.stringify(r.exceptionDetails).slice(0, 500));
    return r.result.value;
  }
}

const clickBack = `(() => {
  const walk = (root, sel, out) => {
    let nodes; try { nodes = root.querySelectorAll("*"); } catch (e) { return out; }
    for (const el of nodes) {
      if (el.matches && el.matches(sel)) out.push(el);
      if (el.shadowRoot) walk(el.shadowRoot, sel, out);
    }
    return out;
  };
  const btns = walk(document, ".mi-back", []);
  if (!btns.length) return "no .mi-back button";
  btns[0].click();
  return "clicked";
})()`;

(async () => {
  const target = await getTarget();
  const ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((r) => ws.addEventListener("open", r, { once: true }));
  const cdp = new CDP(ws);
  await cdp.send("Page.enable");
  await cdp.send("Runtime.enable");
  await cdp.send("Page.navigate", { url: HA_ORIGIN + "/" });
  await sleep(2000);
  const payload = JSON.stringify(TOKENS);
  await cdp.send("Page.addScriptToEvaluateOnNewDocument", { source: `try { localStorage.setItem("hassTokens", ${JSON.stringify(payload)}); } catch (e) {}` });
  await cdp.eval(`localStorage.setItem("hassTokens", ${JSON.stringify(payload)}); 1`);

  // 从「浴室」区域视图进入小厨宝详情
  await cdp.send("Page.navigate", { url: HA_ORIGIN + "/device-cards/bathroom" });
  await sleep(9000);
  console.log("进入浴室视图 URL:", await cdp.eval("location.pathname"));
  const detail = await cdp.eval(`(() => {
    const walk = (root, sel, out) => {
      let nodes; try { nodes = root.querySelectorAll("*"); } catch (e) { return out; }
      for (const el of nodes) {
        if (el.matches && el.matches(sel)) out.push(el);
        if (el.shadowRoot) walk(el.shadowRoot, sel, out);
      }
      return out;
    };
    const cards = walk(document, "mi-device-card", []);
    if (!cards.length) return "no card";
    cards[0].shadowRoot.querySelector(".mi-card").click();
    return cards[0].shadowRoot.querySelector(".mi-name").textContent.trim();
  })()`);
  console.log("点击卡片:", detail);
  await sleep(4000);
  console.log("详情页 URL:", await cdp.eval("location.pathname"));
  console.log("点击返回:", await cdp.eval(clickBack));
  await sleep(4000);
  console.log("返回后 URL:", await cdp.eval("location.pathname"));

  ws.close(); chrome.kill(); process.exit(0);
})().catch((e) => { console.error("ERR", e.message); chrome.kill(); process.exit(1); });
