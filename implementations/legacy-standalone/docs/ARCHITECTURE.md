# 方案 A 架构详解（独立脚本方案）

本文拆解 `deploy.sh` 驱动的 6 步流水线、各阶段内部逻辑，以及所有跨阶段的数据契约。

---

## 一、流水线总览

`deploy.sh` 是幂等的，可反复执行 / 可挂 cron。各步骤之间**没有共享内存**，只靠 `$MI_WORK_DIR`
下的 JSON 文件通信 —— 这是这套架构最关键的约束：任何一步都能单独重跑而不破坏其它步骤的产物。

```
① 刷新令牌    refresh_tokens.py
      ↓ /tmp/ha_tokens.json（前端 localStorage 格式）
② 同步脚本    scp → NAS:/tmp/mi-cards/  +  传 ha_token.txt
      ↓
③ 拉快照      sync.py --stage snapshot   → pull_state.py
      ↓ ha_states.json, ha_registries.json
   生成配置    sync.py --stage generate   → gen_dashboard.py
      ↓ device_dashboard.json, mi-missing-models.json, mi-images.json, mi-cards-state.json
④ 补产品图    fetch_raw_images.py  →  normalize_images.py  →  scp → NAS www/mi-images/
      ↓
⑤ 重新生成    sync.py --stage generate   （这次能看见新图了）
   部署        sync.py --stage deploy     → deploy_device_dashboard.py + bump_resource_version.py
      ↓
⑥ 校验        sync.py --stage verify
```

### 为什么 ④ 之后要「重新生成」

`gen_dashboard.py` 生成面板配置时需要知道每个型号的实物图 URL。首次生成时新品还没抓下来，
只能写占位；抓完图必须再跑一次 generate 才能把真实图片地址写进配置。
`MI_IMG_VER` 环境变量在这一步更新（`int(time.time())`），让图片 URL 的查询串变化以破缓存。

### 为什么 ② 要传 `ha_token.txt` 而不是用环境变量

NAS 上跑 `pull_state.py` / `deploy_device_dashboard.py` 需要访问 HA 的凭据。
access_token 只在 `refresh_tokens.py` 所在的机器上有（它是登录态换来的），
所以第 ② 步通过 `ssh ... "cat > ha_token.txt"` 的方式把 token 文本写进 NAS 的工作目录。
**这是本方案最大的安全弱点**：明文 token 落在磁盘上。

---

## 二、`ha_ws.py` —— 纯标准库 WebSocket 客户端

没有 `websocket-client`、没有 `aiohttp`，只用 `socket` + `base64` + `struct` 手写帧编解码。

```python
class HAWS:
    def __init__(self, host="127.0.0.1", port=8123, token=None): ...
    def _connect(self, path="/api/websocket"): ...   # HTTP Upgrade 握手
    def _send_frame(self, payload, opcode=0x1): ...  # 文本帧
    def _recv_exact(self, n): ...                    # 精确读 n 字节（处理分片）
    def _recv_frame(self): ...                       # 解析帧头 + 掩码解码
    def handshake(self): ...                         # 发 auth 消息，等 auth_ok
    def call(self, cmd, **args): ...                 # 发命令，等 id 匹配的结果
```

### 握手流程

1. TCP 连接 → 发 `GET /api/websocket HTTP/1.1` + `Upgrade: websocket` + `Sec-WebSocket-Key`
2. 读 HTTP 响应头，期望 `101 Switching Protocols`
3. 收第一帧 → `{"type": "auth_required"}`
4. 发 `{"type": "auth", "access_token": token}`
5. 收 `{"type": "auth_ok"}`

### 关键约定

- **WS 命令参数必须在消息顶层**，不能嵌套在 `payload` 里。即：
  `{"id": 1, "type": "config_entries/get", "domain": "mi_cards"}`，
  **不是** `{"id": 1, "type": "...", "payload": {...}}`。
- 服务端可能**主动断开**刚建立的连接（限流 / 负载高）。`pull_state.py` / `deploy_device_dashboard.py`
  / `bump_resource_version.py` 都有 `connect(host, port, token, retries=6)` 重试循环。
- 调用 `homeassistant.restart` 这类会重启自己的服务时，WS 连接会被切断并抛
  `RemoteDisconnected` —— **这是正常现象**，不是失败。判断成功要看服务是否真的执行了
  （例如检查进程 PID 是否变化）。

---

## 三、`pull_state.py` —— 快照采集

拉三样东西，落盘：

| 输出 | 来源命令 | 说明 |
| --- | --- | --- |
| `ha_states.json` | `get_states` | 全量实体状态（list 格式，每项含 `entity_id`/`state`/`attributes`） |
| `ha_registries.json` | `config/entity_registry/list`<br>`config/device_registry/list`<br>`config/area_registry/list` | 三个注册表全量 |

**为什么用快照而不是直接读**：脚本跑在 HA 外部，拿不到 `hass` 对象，只能走 WS 命令。
这也带来固有的时间窗口问题（快照与生成之间设备可能变化）。

---

## 四、`gen_dashboard.py` —— 配置生成器（核心，931 行）

### 输入处理

```python
STATES = {e["entity_id"]: e for e in json.load(open(STATES_FILE))}
ENTS   = REG["entity_registry"]["entities"]
DEVS   = {d["id"]: d for d in REG["device_registry"]["devices"]}
AREAS  = {a.get("area_id") or a["id"]: a["name"] for a in REG["area_registry"]["areas"]}
```

### 内部逻辑分层

```
① 型号识别
   MIOT_RE + BRANDS + KNOWN_MODELS + DID_MODEL
   → 从 entity_id / 设备名 / did 推断设备型号（用于查产品图）
   → split_model(rest, brand, did) 拆解

② 实体清洗
   clean_name(fname, devname)   去掉 _s_数字_ / _p_数字 / _a_数字 这类后缀
   SKIP_KEYWORDS = ["工厂测试", "设备自定义功能", "固件", "spec"]
   → 过滤掉固件更新实体、工厂测试实体等噪声

③ 卡片选主
   pick_main(ents)              选代表实体（决定卡片标题与图标）
   pick_power_switch(ents, main) 选开关实体（圆形按钮绑到它）
   pick_status_sensor(ents, main) 选状态传感器（副标题文本）

④ 离线设备区
   offline_devices() → 固定 key "__offline__"，slug 固定 "offline"
   （设备已注册但实体全部 unavailable 时归入此区）

⑤ 区域聚合
   区域 → 设备列表 → 每设备一张卡
   每个区域一个 view，路径来自 SyncState（稳定 slug）

⑥ 输出
   device_dashboard.json      最终 Lovelace 配置
   mi-images.json             型号 → 图 URL
   mi-missing-models.json     缺图型号清单
```

### 生成的面板结构

与集成方案保持一致的 UX：

- `type: sections` + `max_columns: 4` + 每 section `column_span: 4`
  → 卡片才能铺满整宽。**只写 `cards` 不写 `sections` 会被挤成窄列**，这是踩过的坑。
- 卡片 `aspect-ratio: 1.43 / 1`（横向卡片）
- 圆形按钮放右上角

---

## 五、产品图两段式流水线

```
fetch_raw_images.py                normalize_images.py
  米家百科 realIcon                   content_bbox() 裁出主体
       ↓                                  ↓
  raw/xxx.png  (原图，永不覆盖)      等比缩放
                                       ↓
                                 居中放入 480×480 透明画布
                                       ↓
                                 out/xxx.png (成品)
                                       ↓
                                 scp → NAS www/mi-images/
```

### 为什么必须分两段

百科 `realIcon` 是 480×480，但**每个型号的「主体占比」差异极大**（实测 31% ~ 100%）。
直接用原图放进卡片，会出现「空调是一条线、插头却撑满」的视觉失衡。
标准化会**重写**图片，一旦覆盖原图就无法还原 —— 所以必须先存原图再处理。

### 归一化参数（`normalize_images.py`）

```python
CANVAS    = 480   # 输出画布边长
FILL      = 0.86  # 主体长边占画布比例
WIDE_RATIO= 2.0   # 宽高比超过此值视为「横向长条」（空调/机顶盒等）
WIDE_FILL = 0.92  # 横向长条按宽度归一
MIN_CONTENT = 12  # 主体小于该像素数视为空图，不处理
```

集成方案 `images.py` 沿用了**完全相同**的 5 个常量，以保证两套方案产出的图片观感一致。

---

## 六、破缓存机制

Lovelace 资源注册后，浏览器会长时间缓存（HA 侧 31 天 + 浏览器本地缓存）。
本方案的做法是每次部署都改资源 URL 的查询串：

```python
# bump_resource_version.py
VER = sys.argv[1] if len(sys.argv) > 1 else str(int(time.time()))
# → 把 lovelace 资源项的 url 从 /local/mi-cards.js?v=旧值 改成 ?v=新值
```

时间戳版本的问题是**没有语义**：看不出装的是哪个版本，也无法回滚。
集成方案改成了显式 `?v={VERSION}`（`const.py` 里的 `VERSION = "1.0.1"`），
版本号 bump 即让所有客户端重新拉取。

---

## 七、令牌体系

```
NAS .storage/auth
    │  （refresh_tokens 里存的是 rt["token"]，不是 rt["refresh_token"]！）
    ↓
refresh_token（长期有效）
    ↓  POST /auth/token  grant_type=refresh_token
access_token（30 分钟有效）
    ↓
写入 /tmp/ha_tokens.json（前端 localStorage 的格式：hassUrl / clientId / access_token / expires）
```

`refresh_tokens.py` 通过 `ssh fnos "cat .storage/auth"` 读取 —— 意味着**能读 NAS 配置目录就能拿到管理员长期凭据**。
这是本方案绝对不能公开分发的根本原因。

---

## 八、与集成方案的对应关系

| 本方案 | 集成方案（`../ha-integration/`） | 差异 |
| --- | --- | --- |
| `pull_state.py` + `ha_states.json` | `device_tree.py` 直接读注册表 | 无快照、无时间窗口 |
| `gen_dashboard.py` 生成 YAML | `__init__.py::_build_dashboard_config()` | 同一套视图结构 |
| `sync_state.py` 稳定 slug | `device_tree.py` 里按 area_id 直接推导 | 集成版靠 area_id 天然稳定，不需状态文件 |
| `fetch_raw_images.py` + `normalize_images.py` | `images.py::ImageManager` | 同样两段式，同样 5 个常量 |
| `deploy_device_dashboard.py` 写面板 | `LovelaceStorage.async_save()` | 集成版有用户配置保护 |
| `bump_resource_version.py` | `?v={VERSION}` | 语义化版本号 |
| `refresh_tokens.py` + SSH | `hass` 上下文 | 零凭据 |
| `mi-cards.js`（1091 行） | `static/mi-cards.js`（1400+ 行，多了 `custom:mi-device-wall`） | 前端是同一血脉 |
