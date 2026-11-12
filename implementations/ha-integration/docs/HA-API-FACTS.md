# HA API 事实表（全部经 2026.11.1 源码或实机核验）

> **这份文档是本仓库最有价值的技术资产。**
> 这里的每一条都是踩过坑之后核验出来的，**不要凭直觉改**。
> 核验环境：Home Assistant **2026.11.1**（NAS fnos，192.168.31.67）。

---

## 1. 校验库是 `probatio`，不是 `voluptuous`

HA 2026.11 已把 `voluptuous` 换成了 `probatio`。

```bash
grep -c "voluptuous" homeassistant/helpers/config_validation.py   # → 0
```

导入方式：

```python
import probatio
```

库版本：`probatio==0.13.0`（来自 HA 的 `pyproject.toml`）。

---

## 2. ⚠️ `probatio.to_field_list()` 的可序列化约束

配置流的 `data_schema` 必须能被 `probatio.to_field_list()` 序列化成前端表单字段。
**只接受**这些类型：

```
str / bool / int / float / In / Email / Url / Lower
```

自定义校验函数 **不可序列化**，会抛：

```
ValueError: unable to serialize schema: <function _dashboard_url ...>
```

→ 配置流直接 **500**。

**正确姿势**：schema 里只用 `str` / `bool`，校验逻辑放在流程里：

```python
def _validate(user_input) -> dict[str, str]:
    errors = {}
    if not _valid_url(user_input.get(CONF_DASHBOARD_URL)):
        errors[CONF_DASHBOARD_URL] = "invalid_url"
    return errors

async def async_step_user(self, user_input=None):
    errors = _validate(user_input) if user_input else {}
    if errors:
        return self.async_show_form(step_id="user", data_schema=_schema(defaults), errors=errors)
```

校验成功的表单序列化结果长这样：

```json
[{"type":"string","name":"dashboard_url","required":false},
 {"type":"boolean","name":"show_in_sidebar","required":false}]
```

---

## 3. ⚠️ 服务回调签名是 `func(call)`，**不传 `hass`**

```python
hass.services.async_register(DOMAIN, "refresh", _async_service_refresh)
```

HA 内部会调用 `func(call)` —— 只传 `ServiceCall`。
写成 `(hass, call)` 会报：

```
TypeError: _async_service_refresh() missing 1 required positional argument: 'call'
```

**正确写法**：

```python
async def _async_service_refresh(call: ServiceCall) -> None:
    hass = call.hass        # ← hass 在 call 上
```

`ServiceCall.hass` 属性存在（`homeassistant/core.py` 的 `ServiceCall.__init__`）。

---

## 4. `OptionsFlow.config_entry` 是**属性**

```python
class MiCardsOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input=None):
        current = self.config_entry.data     # ← 属性，不是 self.config_entry()
```

框架在 `homeassistant/config_entries.py` 里自动注入。写成方法调用会报 `TypeError: 'ConfigEntry' object is not callable`。

---

## 5. 配置流 REST 接口：body **直接是表单字段**

```
POST /api/config/config_entries/flow
body: {"handler": "mi_cards", "title": "", "show_advanced_options": false}

→ 返回 flow_id

POST /api/config/config_entries/flow/{flow_id}
body: {"dashboard_url": "device-cards", "accent": "#ff6a00", "show_in_sidebar": true}
```

**不要**包一层 `{"user_input": {...}}` —— 会报：

```json
{"errors": {"base": ["not a valid option at 'user_input'"]}}
```

---

## 6. `Store` —— 持久化键值

```python
from homeassistant.helpers.storage import Store

store = Store(hass, version=1, key="mi_cards_images")
await store.async_load()     # -> dict | None
await store.async_save(data)
```

落盘位置：`<config>/.storage/<key>`。

---

## 7. Lovelace 面板写入

```python
from homeassistant.components.lovelace.const import LOVELACE_DATA
from homeassistant.components.lovelace.dashboard import LovelaceStorage

dashboards = hass.data[LOVELACE_DATA].dashboards       # dict: url_path -> LovelaceConfig
dash = dashboards.get(url_path)
if dash is None:
    dash = LovelaceStorage(hass, {"id": url_path.replace("-", "_"), "url_path": url_path})
    dashboards[url_path] = dash

current = await dash.async_load(False)    # 读现有配置；False = 不报错
await dash.async_save(config)             # 写
```

- 落盘：`<config>/.storage/lovelace.<id>`（`id` 由 `-` 换成 `_`）
- `hass.data[LOVELACE_DATA].dashboards` 是 dict，键是 **url_path**

---

## 8. ⚠️ Lovelace 存储文件的结构是 `data.config.views`

```json
{
  "version": 1,
  "minor_version": 1,
  "key": "lovelace.device_cards",
  "data": {
    "config": {
      "views": [ ... ]        ← ✅ 正确位置
    }
  }
}
```

**不是** `data.views`（那是废弃字段，HA 不读）。
调试时改错位置 → 集成读不到 → 误判保护逻辑失效。

---

## 9. ⚠️ sections 布局必须写全三个字段

```yaml
type: sections
max_columns: 4
sections:
  - type: grid
    column_span: 4       # ← 少了这个，卡片会被挤成窄条一列
    cards: [...]
```

只写 `cards` 不写 `sections` → 前端渲染成单列窄条。实测坑。

---

## 10. Lovelace 资源注册

```python
from homeassistant.components.lovelace import ResourceStorageCollection

item = {"res_type": "module", "url": "/api/mi_cards_static/mi-cards.js?v=1.0.1"}
```

- `res_type` 会被集合内部转成 `type`
- `id` 由集合**自动注入**，不用自己生成
- 落盘：`<config>/.storage/lovelace_resources`
- `?v=` 是缓存键，改 JS 必须 bump 版本号

---

## 11. 内置面板注册

```python
from homeassistant.components import frontend

frontend.async_register_built_in_panel(
    hass, "mi_cards",
    frontend_url_path="device-cards",
    sidebar_title="设备",
    config={"mode": "storage"},
)
```

- `frontend.async_panel_exists(hass, url_path)` 可查重
- 集成本身没做查重，靠 `_has_foreign_content()` 保护（更严格的语义）

---

## 12. 静态资源路径

```python
from homeassistant.components.http import StaticPathConfig

await hass.http.async_register_static_paths([
    StaticPathConfig("/api/mi_cards_static", str(_STATIC_DIR), False)
])
```

第三个参数 `cache_headers=False` → 不缓存。

另外 HA 的 `frontend` 组件会把 `<config>/www` 映射到 `/local`
（`homeassistant/components/frontend/__init__.py`）——
所以产品图放 `<config>/www/mi_cards/images/` 就能用 `/local/mi_cards/images/xxx.png` 访问。

---

## 13. WebSocket 命令注册

```python
from homeassistant.components import websocket_api

websocket_api.async_register_command(hass, ws_device_tree)
```

- **重复注册直接覆盖**，不报错
- 装饰器：

```python
@websocket_api.websocket_command({probatio.Required("type"): "mi_cards/device_tree"})
@websocket_api.async_response
async def ws_device_tree(hass, connection, msg):
    connection.send_result(msg["id"], _build_tree(hass))
```

前端：`hass.callWS({ type: "mi_cards/device_tree" })`

---

## 14. ⚠️ 注册表事件常量**不在** `homeassistant/const.py`

三个常量分别定义在各自的 helper 模块里：

```python
from homeassistant.helpers.area_registry import EVENT_AREA_REGISTRY_UPDATED
from homeassistant.helpers.device_registry import EVENT_DEVICE_REGISTRY_UPDATED
from homeassistant.helpers.entity_registry import EVENT_ENTITY_REGISTRY_UPDATED
```

在 `homeassistant/const.py` 里 import 会 `ImportError`。

---

## 15. ⚠️ `device_registry.devices` 是弃用视图

2026.11 里 `reg.devices` 返回 `_DeprecatedDeviceRegistryItemsView`：

- ✅ `for device in reg.devices:` —— **受支持**
- ❌ `reg.devices.values()` / `reg.devices.get()` —— **已弃用**，`breaks_in_ha_version=2027.9.0`

日志会打：

```
uses device_registry.devices as a mapping ... breaks_in_ha_version=2027.9.0
```

---

## 16. hassfest 校验规则

| 规则 | 说明 |
| --- | --- |
| **`iot_class` 强制** | 自定义集成（`custom_components/`）**必须**声明 `iot_class`，缺失即 error（`script/hassfest/manifest.py` 约 544-549 行） |
| 键序 | 必须是 `domain`, `name`, 然后**字母序** |
| `documentation` | 自定义集成可省略 |
| `codeowners` | 必填 |

---

## 17. 核心依赖不需要写进 `requirements`

HA 2026.11 的 `pyproject.toml` 里已经有：

```
Pillow==13.0.0
probatio==0.13.0
aiohttp==3.14.5
```

所以 `manifest.json` 的 `requirements` 保持 `[]` 即可，不要重复声明 Pillow。

---

## 18. `homeassistant.restart` 服务可用来重启 Core

在无法 `docker restart` 的环境（HAOS / s6 托管、无 docker CLI 权限）里：

```yaml
action: homeassistant.restart
```

会重启 Core 进程（s6 拉起新进程）。**调用它的 WS 连接会被切断并抛 `RemoteDisconnected`，
这是正常现象** —— 判断成功要看进程 PID 是否变化：

```bash
ps -eo pid,lstart,args | grep "m homeassistant" | grep -v grep
```

---

## 19. HA 会主动断开刚建立的 WebSocket

高负载 / 限流时，HA 可能直接关掉刚握手的 WS。做外部 WS 客户端时**必须有重试循环**
（legacy 方案的 `connect(host, port, token, retries=6)` 就是为这个）。

---

## 20. `ConfigEntry` 相关

- `entry.data` / `entry.options` —— 读配置
- `entry.async_on_unload(entry.add_update_listener(cb))` —— 选项变更回调
- `manifest.json` 里 `single_config_entry: true` → 配置流在已有条目时会**中止**（`single_config_entry_abort`），
  框架层支持这个键（`homeassistant/loader.py`）

---

## 快速核验清单（改代码前对照）

```
□ 用到的 API 在这份文档里有记录吗？没有 → 先查 HA 源码再写
□ probatio schema 的字段类型是 str/bool/int/float/In/Email/Url/Lower 吗？
□ 服务回调签名是 func(call) 吗？
□ 前端 JS 改了吗？→ bump const.py 的 VERSION + manifest.json 的 version
□ 根目录 custom_components/ 是镜像吗？→ 改完跑 tools/sync_release.py
□ device_registry.devices 只用迭代，不用 .values()/.get()？
□ 注册表事件常量从 helper 模块 import，不是 homeassistant/const？
□ 新增了 manifest 键 → 检查键序 + iot_class 是否还在
```
