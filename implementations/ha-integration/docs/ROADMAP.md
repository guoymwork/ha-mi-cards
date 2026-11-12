# 方案 B 扩展路线图

> 这份路线图回答一个问题：**下一步要加功能，技术路线怎么选。**
> 每条都给出推荐方案 + 为什么不选另一种 + 落点文件。

---

## P0 —— 稳定性（先做这些）

### 1. 区域 slug 的持久化稳定

**问题**：区域 slug 由 `area_id` 或中文名推导。HA 原生区域 id 在自建时是 UUID
（`a1b2c3d4-...`），一旦推导不出有意义的 slug 就退化成哈希。用户改区域名后，
slug 可能变 → 收藏链接失效。

**现状**：集成版没有 legacy 那套 `SyncState` 状态文件（`../legacy-standalone/docs/STATE-MODEL.md`）。

**推荐路线**：**加一个可选的 slug 持久化层**，用 HA 的 `Store`（不引第三方依赖）：

```python
# 新文件 custom_components/mi_cards/slugs.py
class SlugStore:
    """区域 ID → slug 的持久映射；用户改名时沿用旧 slug。"""
    def __init__(self, hass): self._store = Store(hass, 1, "mi_cards_slugs")
    async def async_load(self): ...
    async def async_get(self, area_id, name) -> str: ...
    async def async_save(self): ...
```

集成点：`device_tree.py::guess_area_slug_and_icon()` 之前先查 `SlugStore`。

**为什么不选 legacy 的做法**：legacy 还要额外存 title / icon / overrides 三份东西，
而集成版可以直接读 HA 原生的 `area.icon` 字段（用户可自己在 UI 里设），
只有 slug 需要持久化。**能从 HA 原生拿到的，就不要自己存。**

**取舍**：slug 持久化会带来「用户删了区域又重建，slug 被复用」的边缘情况。
需要在 `SlugStore` 里记录「该 slug 曾属于哪个 area_id」，重建时按 id 匹配。

---

### 2. 面板路径冲突要能让用户看见

**问题**：`_has_foreign_content()` 检测到路径被占用时，只在日志里打 WARNING。
用户看到的是「面板没出来」，却不知道为什么。

**推荐路线**：用 HA 的持久通知：

```python
from homeassistant.components import persistent_notification

persistent_notification.async_create(
    hass,
    message=f"面板路径 {url_path} 已被你自己的面板占用，集成已跳过写入。请在集成配置里换一个路径。",
    title="米家风格设备面板",
    notification_id="mi_cards_dashboard_conflict",
)
```

**落点**：`__init__.py::_async_write_dashboard()` 的冲突分支。

---

### 3. 大户型性能

**问题**：`_build_tree()` 会遍历所有实体并做大量正则匹配。200+ 设备的家庭，
首屏构建可能到几百毫秒。

**推荐路线**：
1. 先测量（`time.monotonic()` 包一下 `_build_tree`）再优化，不要凭感觉改。
2. 若确实慢：把正则预编译成模块级常量（已经是了），并考虑把 `_build_detail()`
   的重活延后 —— 详情行只在卡片被点开时才算。

**关键设计**：详情数据目前是**一次性全量算好**放在树里。
改成懒加载需要新增 WS 命令 `mi_cards/device_detail`，前端点卡片时再拉。

**为什么不选**：懒加载会引入「点开有 loading 态」的复杂度。
在实测数据出来之前不做。

---

## P1 —— 功能扩展

### 4. 实体筛选器：控制哪些实体显示为卡片

**问题**：现在一个 `device` 就是一张卡。但一个米家设备往往有多个实体
（开关 + 温度 + 湿度），用户可能只想看到其中几个。

**推荐路线**：在配置流加一个「实体筛选」选项，存一份 `entity_id` 白名单：

```python
CONF_ENTITY_FILTER: Final = "entity_filter"   # list[str]
```

`device_tree.py` 构建时按白名单过滤主实体候选。

**为什么不选「一实体一卡」**：会得到大量重复卡片（同一台机器 5 张卡），破坏米家那种「一个设备一张卡」的直觉。

---

### 5. 设备详情浮层支持更多实体类型

**现状**：详情行支持开关、档位、动作按钮、红外开关。

**推荐路线**：按 `domain` 分派渲染器，而不是按属性名猜：

```python
DETAIL_RENDERERS = {
    "switch": _render_switch,
    "light":  _render_light,
    "cover":  _render_cover,
    "lock":   _render_lock,
    "fan":    _render_fan,
    "climate": _render_climate,
}
```

`cover` 要处理 `current_position`（百分比）、`lock` 要处理 `code`（需要输入密码）。

**为什么不选插件式渲染器**：过度设计，YAGNI。直接 map 足够。

---

### 6. 多面板支持

**问题**：一个集成条目只能生成一个面板。用户可能想要「设备」和「场景」两个面板。

**推荐路线**：把 `dashboard_url` 从字符串改成列表会破坏配置流兼容性。
更好的做法是**支持多个 config entry** —— 但 manifest 里现在是 `single_config_entry: true`。

**决策点**：如果要支持多面板，需要去掉 `single_config_entry`，
并让 `async_setup_entry` 支持多条目共存（面板路径去重）。

**权衡**：`single_config_entry: true` 能防止重复添加导致的路径冲突。
若要支持多面板，改为在 `_async_write_dashboard` 里做路径占用检查（已有）。

---

### 7. 产品图的用户本地覆盖

**问题**：某些设备百科没收录，或用户想要自己的图。

**推荐路线**：约定一个覆盖目录，用户把图按型号命名放进去即可：

```
<config>/www/mi_cards/images/overrides/<safe_model>.png
```

`ImageManager.url_for()` 优先查覆盖目录。

**为什么不选**：上传 UI —— 要加媒体库依赖，复杂度不划算。

---

### 8. 卡片内嵌迷你趋势图

**问题**：现在卡片只有「开 / 关」文字状态，看不到历史。

**推荐路线**：用 HA 自带 `<ha-sparkline>` 元素（前端内置，无需额外资源）：

```html
<ha-sparkline .data=${points} .graphType=${"line"}></ha-sparkline>
```

数据来源：调用 `history/period/<timestamp>` REST 接口拿最近 24 小时。

**风险**：HA App 里 `<ha-sparkline>` 在自定义卡片 shadow DOM 中的表现需要真机验证。

---

## P2 —— 架构

### 9. 把设备树暴露为 HA 实体

**问题**：目前设备树只能通过 WS 命令拿，其他自动化用不了。

**推荐路线**：加一个 `sensor` 平台，提供：

| 实体 | 内容 |
| --- | --- |
| `sensor.mi_cards_device_count` | 设备总数 |
| `sensor.mi_cards_offline_count` | 离线设备数 |
| `sensor.mi_cards_area_list` | 区域列表（JSON） |

**为什么不选把整棵树塞进一个 attribute**：会频繁触发状态更新，污染历史记录。

---

### 10. 前端文案 i18n

**问题**：前端现在是硬编码中文（区域名来自 HA 所以没问题，但「全部」「离线」等是硬编码）。

**推荐路线**：用 `hass.localize()` + 前端自己的文案表：

```js
const T = {
  all: () => hass.localize("mi_cards.all") || "全部",
  offline: () => hass.localize("mi_cards.offline") || "离线",
};
```

配合 `translations/*.json` 的 `component.mi_cards.*` 段。

---

### 11. 实体级配置（而非全局）

**问题**：现在是「整个集成一个 accent / 面板路径」，无法给不同区域不同主色。

**推荐路线**：在 `device_tree.py` 的区域输出里带上 `accent` 字段（可由 `area` 属性的
`icon`/`name` 推导，或后续支持 `mi_cards.areas` 配置段），前端按区域取色。

---

## 不建议做的事

| 想法 | 为什么不做 |
| --- | --- |
| 前端改用 lit / TypeScript + 构建 | 会破坏「装上就能用、零工具链」的核心优势 |
| 把设备树缓存到磁盘 | 注册表是实时的，缓存只会带来一致性问题 |
| 自己实现 Lovelace 资源版本管理 | `?v={VERSION}` 已经够用 |
| 在集成里跑 cron / 定时任务 | HA 的事件机制已经覆盖（注册表变化 → 事件 → 重建） |
| 支持非米家设备 | 设备树是从注册表算的，理论上通用；但产品图依赖米家百科，混合场景的取舍要重新设计 |

---

## 提交前自检

改了本方案的代码后：

```
□ 读 HA-API-FACTS.md，确认用到的 API 行为没变
□ 改了前端 → bump VERSION + 同步 manifest.json
□ 跑 tools/sync_release.py
□ 按 docs/TESTING.md 的验收清单过一遍
□ 更新本文件的路线图（做掉的划掉）
```
