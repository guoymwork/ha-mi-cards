/**
 * 详情页布局体检：遍历 mi-device-detail 内部所有可见元素，检测是否互相叠压
 * 用法: node cdp-detail-layout.mjs <详情页URL> [宽] [高] [输出JSON]
 */
import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const TARGET = process.argv[2] || "http://ha.local:8123/device-cards/%E7%B1%B3%E5%AE%B6%E6%99%BA%E8%83%BD%E5%B0%8F%E5%8E%A87l-s1";
const W = Number(process.argv[3] || 1440);
const H = Number(process.argv[4] || 1200);
const OUTJSON = process.argv[5] || "";
const HA_ORIGIN = process.env.HA_ORIGIN || "http://ha.local:8123";
const PORT = 9300 + Math.floor(Math.random() * 250);

const TOKENS = JSON.parse(fs.readFileSync("/tmp/ha_tokens.json", "utf8"));
TOKENS.expires = Date.now() + (TOKENS.expires_in || 1800) * 1000;

const CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const profile = fs.mkdtempSync(path.join(os.tmpdir(), "ha-det-"));
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

const JS = `(() => {
  const walk = (root, sel, out) => {
    let nodes; try { nodes = root.querySelectorAll("*"); } catch (e) { return out; }
    for (const el of nodes) {
      if (el.matches && el.matches(sel)) out.push(el);
      if (el.shadowRoot) walk(el.shadowRoot, sel, out);
    }
    return out;
  };
  const d = walk(document, "mi-device-detail", [])[0];
  if (!d) return {found:false, url: location.href, bodyText: document.body.innerText.slice(0,300)};
  const root = d.shadowRoot;
  // 取有意义的块级元素（排除纯文本/图标）
  const blocks = [...root.querySelectorAll("div,section,header,footer,ul,li,button,img,svg")]
    .filter(el => {
      const cs = getComputedStyle(el);
      if (cs.display === "none" || cs.visibility === "hidden" || cs.position === "absolute") return false;
      const r = el.getBoundingClientRect();
      return r.width > 8 && r.height > 8;
    })
    .map(el => {
      const r = el.getBoundingClientRect();
      return {
        tag: el.tagName.toLowerCase() + "." + (String(el.className||"").split(" ").filter(Boolean).join(".")),
        x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height),
        right: Math.round(r.right), bottom: Math.round(r.bottom),
        txt: (el.textContent||"").trim().slice(0,24),
      };
    });
  // 只比较「互不包含」的元素对：真正叠压 = 交集面积大且两者不是祖先关系
  const overlaps = [];
  for (let i=0;i<blocks.length;i++){
    for (let j=i+1;j<blocks.length;j++){
      const A=blocks[i], B=blocks[j];
      const ox = Math.min(A.right,B.right)-Math.max(A.x,B.x);
      const oy = Math.min(A.bottom,B.bottom)-Math.max(A.y,B.y);
      if (ox>6 && oy>6){
        // 判断是否祖先包含
        const anc = (a,b) => a.x<=b.x && a.y<=b.y && a.right>=b.right && a.bottom>=b.bottom;
        if (!anc(A,B) && !anc(B,A)) {
          overlaps.push({a:A.tag+"["+A.txt+"]", b:B.tag+"["+B.txt+"]", ox:Math.round(ox), oy:Math.round(oy)});
        }
      }
    }
  }
  const wrap = root.querySelector(".mi-wrap");
  const wr = wrap?.getBoundingClientRect();
  return {
    found: true, url: location.href, vw: innerWidth,
    wrap: wr ? {x:Math.round(wr.x), w:Math.round(wr.width), h:Math.round(wr.height)} : null,
    scrollH: wrap?.scrollHeight, clientH: wrap?.clientHeight,
    overflowY: wrap ? wrap.scrollHeight - wrap.clientHeight : null,
    blocks, overlaps: overlaps.slice(0,40),
    overlapCount: overlaps.length,
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
  await sleep(9000);

  const res = await cdp.eval(JS);
  console.log("RESULT:", JSON.stringify(res, null, 2));
  if (OUTJSON) fs.writeFileSync(OUTJSON, JSON.stringify(res, null, 2));

  const shot = await cdp.send("Page.captureScreenshot", { format: "png", captureBeyondViewport: true });
  const png = OUTJSON ? OUTJSON.replace(/\.json$/, ".png") : "/tmp/detail-check.png";
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
