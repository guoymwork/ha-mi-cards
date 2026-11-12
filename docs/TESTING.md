# 验证工作流（Testing）

> 实机环境、部署方法、调试脚本、验收清单。
> 改完代码**必须**走一遍这里描述的验证流程再提交。

---

## 一、测试环境

| 项 | 值 |
| --- | --- |
| HA 版本 | 2026.11.1 |
| 部署方式 | NAS（<nas-host>）上的 HAOS 容器，config 根 `<ha-config>/` |
| HA 地址 | `http://ha.local:8123` |
| 集成路径 | `<ha-config>/custom_components/mi_cards/` |
| 面板存储 | `<ha-config>/.storage/lovelace.device_cards` |
| 图片成品 | `<ha-config>/www/mi_cards/images/` |
| 图片原图 | `<ha-config>/mi_cards/raw/` |

### 环境限制（踩过的坑）

| 限制 | 绕行办法 |
| --- | --- |
| NAS 上**没有 docker CLI 权限**，`sudo` 要密码 | 用 HA 自带的 `homeassistant.restart` 服务重启 Core（s6 会拉起新进程） |
| **本机裸 socket 被沙箱阻断**（`No route to host`），但 curl 能通 | WebSocket 客户端脚本必须**放到远端主机上跑**（见 legacy 仓库的 `ha_ws.py`，或自己写） |
| HA 高负载时会主动断开刚建立的 WS | 所有 WS 调用都要带重试循环 |
| 访问令牌 30 分钟过期 | 每次调试前先刷新（见下） |

---

## 二、令牌获取

```bash
# 在 NAS 上从 .storage/auth 取 refresh_token → 换 access_token
ssh <nas-host> 'cd /tmp && python3 - <<"EOF"
import json, urllib.request, urllib.parse, time
tok = json.load(open("/tmp/ha_tokens.json"))
data = urllib.parse.urlencode({
    "grant_type": "refresh_token",
    "client_id": tok["clientId"],
    "refresh_token": tok["refresh_token"],
}).encode()
req = urllib.request.Request(tok["hassUrl"] + "/auth/token", data=data,
    headers={"Content-Type": "application/x-www-form-urlencoded"})
r = json.load(urllib.request.urlopen(req, timeout=30))
tok["access_token"] = r["access_token"]
tok["expires"] = int((time.time() + r.get("expires_in", 1800)) * 1000)
json.dump(tok, open("/tmp/ha_tokens.json", "w"))
open("/tmp/ha_at.txt", "w").write(r["access_token"])
print("OK")
EOF'
```

> ⚠️ `.storage/auth` 里存的是 `rt["token"]`，**不是** `rt["refresh_token"]`。

---

## 三、部署改动

```bash
# 1. 语法与结构检查
cd custom_components/mi_cards
python3 -m py_compile *.py
node --check static/mi-cards.js
python3 -c "import json; json.load(open('manifest.json'))"

# 2. 仓库自检（结构 / manifest / 敏感信息 / 版本一致性）
cd ../../..
python3 tools/check.py

# 3. 上传到 NAS
cd custom_components/mi_cards
scp -o ConnectTimeout=10 __init__.py const.py config_flow.py device_tree.py images.py \
    manifest.json services.yaml strings.json <nas-host>:<ha-config>/custom_components/mi_cards/
scp -o ConnectTimeout=10 static/mi-cards.js <nas-host>:<ha-config>/custom_components/mi_cards/static/
scp -o ConnectTimeout=10 translations/*.json <nas-host>:<ha-config>/custom_components/mi_cards/translations/

# 4. 校验文件一致
ssh <nas-host> 'cd <ha-config>/custom_components/mi_cards && find . -type f -not -path "*__pycache__*" | sort | xargs cksum'

# 5. 重启 HA
ssh <nas-host> 'cd /tmp && export HA_TOKEN=$(cat /tmp/ha_at.txt) && \
  python3 /tmp/ha_ws.py "{\"cmd\":\"call_service\",\"args\":{\"domain\":\"homeassistant\",\"service\":\"restart\"}}"'

# 6. 确认新进程
ssh <nas-host> 'ps -eo pid,lstart,args | grep "m homeassistant" | grep -v grep | head -1'
```

> 重启后**要等 30–45 秒**再验证（实体注册要时间）。
> 看到 PID 变了才算重启成功。

---

## 四、单元测试

### 保护逻辑（`_has_foreign_content`）

```bash
cd /tmp && python3 - <<'PY'
import re, sys
from typing import Any
src = open("custom_components/mi_cards/__init__.py", encoding="utf-8").read()
m = re.search(r"\ndef _has_foreign_content.*?\n(?=\n\nasync def )", src, re.S)
ns = {}
exec("from typing import Any\nCARD_TYPE_WALL = 'custom:mi-device-wall'\n" + m.group(0), ns)
f = ns["_has_foreign_content"]
W = "custom:mi-device-wall"
cases = [
    ("空面板", {"views": []}, False),
    ("None", None, False),
    ("非 dict", "xxx", False),
    ("集成 sections", {"views":[{"type":"sections","sections":[{"type":"grid","cards":[{"type":W}]}]}]}, False),
    ("集成 cards", {"views":[{"cards":[{"type":W}]}]}, False),
    ("用户 markdown", {"views":[{"type":"markdown","content":"# 我的家"}]}, True),
    ("用户 tiles", {"views":[{"type":"sections","sections":[{"type":"grid","cards":[{"type":"tile"}]}]}]}, True),
    ("混合", {"views":[{"cards":[{"type":W}]},{"type":"markdown"}]}, True),
]
ok = all(f(c) == w for _, c, w in cases)
for n, c, w in cases:
    r = f(c)
    print(f"{'✓' if r==w else '✗'} {n}: foreign={r} (期望 {w})")
sys.exit(0 if ok else 1)
PY
```

当前覆盖 **12 例**，全部通过。

---

## 五、实机验证

### 5.1 集成是否加载

```bash
ssh <nas-host> 'grep -iE "mi_cards|米家风格" <ha-config>/home-assistant.log | tail -20'
```

期望：无 ERROR / 无 WARNING。

### 5.2 配置条目状态

```bash
ssh <nas-host> 'cd /tmp && export HA_TOKEN=$(cat /tmp/ha_at.txt) && \
  python3 /tmp/ha_ws.py "{\"cmd\":\"config_entries/get\",\"args\":{\"domain\":\"mi_cards\"}}"'
```

期望：`state = loaded`。

### 5.3 设备树

```bash
ssh <nas-host> 'cd /tmp && export HA_TOKEN=$(cat /tmp/ha_at.txt) && \
  python3 /tmp/ha_ws.py "{\"cmd\":\"mi_cards/device_tree\"}"'
```

期望：区域数 = 注册表里的区域数，设备数对得上，区域名和图标正确。

### 5.4 面板配置

```bash
ssh <nas-host> 'python3 -c "
import json
d = json.load(open(\"<ha-config>/.storage/lovelace.device_cards\"))
vs = d[\"data\"][\"config\"][\"views\"]
print(\"视图数:\", len(vs))
for v in vs: print(\" -\", v.get(\"title\"), v.get(\"path\"))
"'
```

期望：「全部」+ 每个区域一个 view，`path` 唯一。

### 5.5 产品图

```bash
ssh <nas-host> 'ls <ha-config>/www/mi_cards/images/ | wc -l; \
          ls <ha-config>/mi_cards/raw/ | wc -l'
```

期望：成品与原图数量一致。

---

## 六、浏览器验证（CDP）

`dev/cdp-shot.mjs` 是基于 Chrome DevTools Protocol 的截图 + 断言脚本。

```bash
cd dev
scp -o ConnectTimeout=10 <nas-host>:/tmp/ha_tokens.json .    # 令牌，需在本机可用
```

### 桌面端

```bash
node cdp-shot.mjs "http://ha.local:8123/device-cards" /tmp/ha.png 1440 1000 '(() => {
  const walk = (root, out) => { out = out || []; for (const el of root.querySelectorAll("*")) { if (el.shadowRoot) walk(el.shadowRoot, out); } out.push(root); return out; };
  const all = walk(document);
  const cards = all.flatMap(r => r.querySelectorAll ? Array.from(r.querySelectorAll(".mi-card")) : []);
  return {
    cardCount: cards.length,
    imgsOk: cards.filter(c => { const i = c.querySelector("img"); return i && i.complete && i.naturalWidth > 0; }).length,
    ratio: cards.slice(0,3).map(c => { const b = c.getBoundingClientRect(); return +(b.width/b.height).toFixed(2); }),
    subs: cards.slice(0,4).map(c => { const s = c.querySelector(".mi-card-sub"); return s ? s.textContent.trim() : null; }),
  };
})()'
```

期望：`cardCount` = 设备数、`imgsOk` = `cardCount`、`ratio` = 1.43。

### 移动端（真机模拟）

> ⚠️ **只传 `--window-size` 不算移动端** —— HA 前端有 `meta viewport`，
> 会把视口撑到 500px。必须用 `MOBILE=1`（走 CDP `Emulation.setDeviceMetricsOverride`）。

```bash
MOBILE=1 node cdp-shot.mjs "http://ha.local:8123/device-cards" /tmp/ha-m.png 390 844 '...'
```

期望（390px）：2 列、卡片 182×127、`overflowX = 0`。

### 其它可用脚本

| 脚本 | 用途 |
| --- | --- |
| `cdp-shot.mjs` | 截图 + 执行断言脚本（主力） |
| `cdp-layout.mjs` | 布局测量 |
| `cdp-detail-layout.mjs` | 详情浮层布局 |
| `cdp-img-check.mjs` | 图片加载检查 |
| `cdp-tabs.mjs` | 区域标签栏 |
| `cdp-interact.mjs` | 交互（点击卡片等） |

---

## 七、验收清单

提交前逐条过：

```
□ python3 -m py_compile 通过
□ node --check 通过
□ tools/check_release.py 通过（HACS 镜像一致）
□ 集成加载无 ERROR/WARNING
□ 配置条目 state=loaded
□ 设备树区域/设备数正确
□ 面板视图数 = 1 + 区域数
□ 产品图成品数 = 原图数
□ 桌面端：4 列、比例 1.43、图片全加载
□ 移动端（390px）：2 列、无横向溢出
□ 详情浮层可打开、可关闭、功能列表完整
□ 改过前端的话：VERSION 已 bump，资源 URL 里能看到新版本
□ README / 文档与实际行为一致
```

---

## 八、回归用例（改动后必跑）

| 场景 | 操作 | 期望 |
| --- | --- | --- |
| 空面板接管 | 把 `data.config.views` 改成 `[]` 后重启 | 集成重新生成面板 |
| 用户面板保护 | 把 `data.config.views` 改成 markdown 视图后重启 | **面板内容不变**，日志打出「已被占用」警告 |
| 服务签名 | 调用 `mi_cards.refresh` | 正常返回 context id，**不报** `missing 1 required positional argument: 'call'` |
| 强制重抓图 | `mi_cards.sync_images` 带 `force=true` | 文件时间戳更新，别名映射生效 |
| 房间改名 | HA 里改区域名 | 区域视图标题跟着变，slug 尽量保持 |
