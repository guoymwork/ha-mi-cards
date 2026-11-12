# 方案 B 架构详解（HA custom integration）

本文拆解集成的模块职责、生命周期、面板与资源写入协议。
所有 API 行为都已对照 HA 2026.11.1 源码核验，细节见 `HA-API-FACTS.md`。

---

## 一、模块职责

| 文件 | 职责 | 不负责 |
| --- | --- | --- |
| `__init__.py` | 生命周期编排、静态资源注册、WS 命令、Lovelace 面板写入、注册表监听、服务 | 不碰设备树算法，不碰图片 |
| `const.py` | 全部常量：域名、版本号、WS 类型、事件名、配置项名、百科 API | 无逻辑 |
| `device_tree.py` | 从三个注册表现算设备树 | 不写盘、不发事件 |
| `images.py` | 抓百科图 + Pillow 归一化 + 落盘 + 索引管理 | 不知道设备树 |
| `config_flow.py` | 配置流 / 选项流 UI | 不含业务逻辑 |
| `static/mi-cards.js` | 前端卡片 | 不含 Python 逻辑 |

**分层原则**：`device_tree.py` 和 `images.py` 都是**纯函数式**的、可脱离 HA 单测；
`__init__.py` 只做编排与副作用（写盘、发事件、注册命令）。

---

## 二、生命周期

```python
async def async_setup(hass, config) -> bool:
    return True          # 只声明依赖，不做实际动作

async def async_setup_entry(hass, entry) -> bool:
    images = ImageManager(hass)
    await images.async_load()                  # 从 Store 载入图片索引，清理失效条目

    # 1) 前端 JS 走 HTTP 静态路径
    await hass.http.async_register_static_paths([
        StaticPathConfig("/api/mi_cards_static", str(_STATIC_DIR), False)
    ])

    # 2) 注册 WS 命令
    websocket_api.async_register_command(hass, ws_device_tree)

    # 3) 注册 Lovelace 资源（module 类型）
    await _async_register_resource(hass)

    # 4) 等实体就绪后再写面板
    _schedule_initial_dashboard(hass, entry)

    # 5) 监听三个注册表的变化
    hass.bus.async_listen(EVENT_AREA_REGISTRY_UPDATED, ...)
    hass.bus.async_listen(EVENT_DEVICE_REGISTRY_UPDATED, ...)
    hass.bus.async_listen(EVENT_ENTITY_REGISTRY_UPDATED, ...)

    # 6) 注册服务
    hass.services.async_register(DOMAIN, "sync_images", _async_service_sync_images)
    hass.services.async_register(DOMAIN, "refresh", _async_service_refresh)

    # 7) 选项变更 → 重建面板
    entry.async_on_unload(entry.add_update_listener(_async_entry_updated))
    return True
```

### 为什么面板要「等实体就绪」再写

集成加载时，其它集成（米家、插座…）可能还没创建实体，`hass.states` 是空的，
此时算出的设备树是空的 —— 如果直接写盘，会得到一个**只有「全部」一个空视图**的面板。

```python
def _schedule_initial_dashboard(hass, entry):
    async def _write_when_ready(now=None):
        if not _has_devices(hass):
            # 实体还没就绪 → 30 秒后重试
            hass.async_create_task(_write_when_ready(datetime.now() + timedelta(seconds=30)))
            return
        await _async_write_dashboard(hass, entry)
    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _write_when_ready)
```

同理，注册表变化后也走 3 秒防抖再重算（`_schedule_dashboard_update`），
避免批量导入设备时写几十次盘。

---

## 三、设备树（`device_tree.py`）

### 输入

三个注册表 + `hass.states`：

```python
ent_reg = er.async_get(hass)     # entity_registry
dev_reg = dr.async_get(hass)     # device_registry
area_reg = ar.async_get(hass)    # area_registry
```

### 输出结构

```json
{
  "areas": [
    {
      "id": "living_room", "name": "客厅", "slug": "living", "icon": "mdi:sofa",
      "devices": [ /* 设备数组 */ ]
    }
  ],
  "devices": { "<device_id>": { /* 设备详情 */ } },
  "other": [ /* 未分配区域的设备 */ ]
}
```

### 内部处理链

```
_build_device()      一个设备 → 主实体 / 开关实体 / 状态传感器 / 详情行
_pick_main()         选代表实体（决定卡片标题与图标）
_pick_power_switch() 选开关实体（圆形按钮绑到它）
_pick_status_sensor()选状态传感器（副标题文本）
_refine_water_heater()  热水器特例：把「温度」等子传感器提到主属性
_merge_dock_devices()    合并「基站 + 机器人」这类多设备实体组
```

### 过滤规则

```python
SKIP_KEYWORDS = ("工厂测试", "设备自定义功能", "固件", "spec", "Spec")
INCLUDE_PREFIX = (...)   # 只保留这些前缀的实体
MAIN_RE  = re.compile(r"_s_\d+_")    # 主实体
PROP_RE  = re.compile(r"_p_\d+")     # 属性
ACT_RE   = re.compile(r"_a_\d+")     # 动作
IR_ON_RE  = re.compile(r"_turn_on_a_")
IR_OFF_RE = re.compile(r"_turn_off_a_")
```

米家实体的 `entity_id` 形如 `switch.living_room_lamp_s_1`，
`s_1` 后缀是主实体，`p_1` 是属性，`a_1` 是动作 —— 这套正则决定了卡片绑哪个实体。

### 缓存

`__init__.py::_build_tree()` 带 30 秒 TTL（`TREE_CACHE_TTL`），
注册表事件会立刻 `_invalidate_tree()` 清掉缓存 —— TTL 只是兜底。

---

## 四、WebSocket 协议

### 命令：`mi_cards/device_tree`

```python
@websocket_api.websocket_command({probatio.Required("type"): WS_TYPE_DEVICE_TREE})
@websocket_api.async_response
async def ws_device_tree(hass, connection, msg):
    connection.send_result(msg["id"], _build_tree(hass))
```

前端调用：

```js
const tree = await hass.callWS({ type: "mi_cards/device_tree" });
```

### 事件：`mi_cards/tree_updated`

设备树变化时通过事件总线广播，前端订阅后自动重建：

```js
hass.connection.subscribeMessage(
  (msg) => rebuild(msg),
  { type: "subscribe_events", event_type: "mi_cards/tree_updated" }
);
```

触发时机：注册表变化（3 秒防抖后）、`mi_cards.refresh` 服务。

---

## 五、面板写入协议

### 面板骨架

```python
{
  "type": "sections",
  "title": "客厅", "path": "living", "icon": "mdi:sofa",
  "show_icon_and_title": True,
  "max_columns": 4,
  "sections": [
    {"type": "grid", "column_span": 4, "cards": [{"type": "custom:mi-device-wall", ...}]}
  ]
}
```

**`max_columns: 4` + `column_span: 4` 两个都要有**，否则卡片被挤成窄列一列（实测坑）。

### 写入流程

```python
async def _async_write_dashboard(hass, entry):
    _invalidate_tree(hass)
    tree = _build_tree(hass)
    if not tree.get("devices"):
        return                       # 空树保护：不覆盖已有面板

    config = _build_dashboard_config(tree, _accent(entry))

    dashboards = hass.data[LOVELACE_DATA].dashboards
    dash = dashboards.get(url_path)
    if dash is None:
        dash = LovelaceStorage(hass, {"id": url_path.replace("-", "_"), "url_path": url_path})
        dashboards[url_path] = dash

    current = await dash.async_load(False)      # 读现有配置

    if current is not None and not _is_managed(current):
        _LOGGER.warning("面板路径 %s 已被占用且不是本集成创建的，已跳过写入…", url_path)
        return                                    # ★ 保护用户配置

    if current != config:
        await dash.async_save(config)             # 内容一致则不写盘，避免前端无谓刷新
```

### `_has_foreign_content()` —— 用户配置保护

判定逻辑：**只有当面板里存在非本集成生成的内容时，才判定为「用户的」并保护**。

```python
for view in views:
    if not isinstance(view, dict):
        return True                      # 无法识别的结构 → 保守保护
    cards = view.get("cards") or []
    if not _has_wall(cards):
        return True
    for section in view.get("sections") or []:
        if not isinstance(section, dict) or not _has_wall(section.get("cards")):
            return True
return False
```

语义：

| 面板内容 | 判定 | 行为 |
| --- | --- | --- |
| 空 / 无 views | 非外来内容 | ✅ 接管 |
| 全是 `custom:mi-device-wall` | 非外来内容 | ✅ 接管并更新 |
| 用户的 markdown 视图 | 外来内容 | ⛔ 跳过 + WARNING |
| 混合（集成 + 用户） | 外来内容 | ⛔ 跳过 + WARNING |

单元测试 12 例覆盖，已在真机双向验证（空面板被接管 / 用户面板被完整保留）。

---

## 六、前端资源注册

```python
async def _async_register_resource(hass):
    await _async_ensure_loaded(resources)
    item = {"res_type": "module", "url": f"{CARD_JS_URL}?v={VERSION}"}
    # 已存在同 url 的则更新 url（用于 bump 版本号破缓存）
    # 旧版遗留的 "/local/mi-cards.js" 资源会被清理
```

- `res_type` 会被 `ResourceStorageCollection` 转成 `type`
- `id` 由集合自动注入，不用自己生成
- `?v={VERSION}` 是**缓存键**：改前端 JS 必须 bump `const.py` 的 `VERSION`
  （并同步 `manifest.json` 的 `version`），否则浏览器拿旧文件

---

## 七、产品图管理（`images.py`）

### 目录

```
<config>/mi_cards/raw/          原图（永不覆盖）
<config>/www/mi_cards/images/   成品（HA 通过 /local 暴露）
<config>/.storage/mi_cards_images   索引（型号 → 文件名 + 哈希）
```

### 两段式流程

```python
async def async_sync(self, models, force=False) -> dict[str, Any]:
    # 1) 查索引，命中的直接跳过（除非 force）
    # 2) 并发抓百科图（_FETCH_CONCURRENCY=3, _FETCH_DELAY=0.25）
    # 3) Pillow 归一化（_normalize_file）
    # 4) 写成品 + 记录哈希
```

### 关键细节

- **标准化在 `hass.async_add_executor_job` 里跑**，不阻塞事件循环
- **重试**：`_FETCH_RETRIES=4`，退避 `_FETCH_BACKOFF=1.5`
  （米家百科会偶发 `RemoteDisconnected`）
- **区分「未收录」与「请求失败」**：`_async_baike()` 返回 `(name, icon, reachable)` 三元组
  —— 前者是真的没这个型号，后者是网络问题需要重试
- **别名映射**：`BAIKE_ALIAS = {"roborock.vacuum.a134": "roborock.vacuum.p5", ...}`
- **归一化常量与 legacy 方案完全一致**（`CANVAS=480 FILL=0.86 WIDE_RATIO=2.0 WIDE_FILL=0.92 MIN_CONTENT=12`）
- `url_for(model)` 返回 `/local/mi_cards/images/xxx.png?v=<sha1[:10]>` —— 用内容哈希做缓存键

---

## 八、服务实现

```python
hass.services.async_register(DOMAIN, "sync_images", _async_service_sync_images)
hass.services.async_register(DOMAIN, "refresh", _async_service_refresh)
```

> ⚠️ **回调签名是 `func(call)`，不传 `hass`** —— 这是踩过的坑。
> `hass` 从 `call.hass` 取。写成 `(hass, call)` 会报
> `missing 1 required positional argument: 'call'`。

---

## 九、配置流（`config_flow.py`）

```python
probatio.Schema({
    probatio.Optional(CONF_DASHBOARD_URL, default=...): str,
    probatio.Optional(CONF_DASHBOARD_TITLE, default=...): str,
    probatio.Optional(CONF_ACCENT, default=...): str,
    probatio.Optional(CONF_SHOW_IN_SIDEBAR, default=...): bool,
    probatio.Optional(CONF_AUTO_SYNC_IMAGES, default=...): bool,
})
```

> ⚠️ **字段类型只能用 `str` / `bool` / `int` / `float` / `In` / `Email` / `Url` / `Lower`**。
> 自定义校验函数无法被 `probatio.to_field_list()` 序列化，会抛
> `ValueError: unable to serialize schema` → 配置流 500。
>
> **校验逻辑要放在流程里**（`_validate()`），用 `async_show_form(..., errors=errors)` 回显。

`OptionsFlow.config_entry` 是**属性**（由框架注入），不是方法。

---

## 十、依赖与清单

```json
{
  "domain": "mi_cards",
  "name": "米家风格设备面板",
  "codeowners": ["@guoymwork"],
  "config_flow": true,
  "dependencies": ["frontend", "http", "lovelace", "websocket_api"],
  "integration_type": "service",
  "iot_class": "local_push",
  "requirements": [],
  "single_config_entry": true,
  "version": "1.0.1"
}
```

- `iot_class` 是 **hassfest 对自定义集成的强制项**，缺了 HACS 校验直接 error
- `requirements: []` —— `Pillow`（13.0.0）与 `probatio`（0.13.0）都是 HA 核心依赖，不用重复声明
- manifest 键序必须是 **domain, name, 然后字母序**
