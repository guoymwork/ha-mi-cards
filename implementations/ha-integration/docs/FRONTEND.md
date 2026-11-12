# 前端卡片体系（`static/mi-cards.js`）

> 纯原生 JS，**无 lit、无构建、无 npm**。单文件，直接作为 Lovelace `module` 资源加载。
> 这是刻意的选择：让集成「装上就能用」，不引入任何前端工具链。

---

## 一、四个自定义元素

| 元素 | 卡片类型 | 职责 |
| --- | --- | --- |
| `MiDeviceCard` | `custom:mi-device-card` | 单张设备卡：实物图 + 名称 + 状态副标题 + 右上角圆形按钮 |
| `MiDeviceDetail` | `custom:mi-device-detail` | 设备详情浮层：温度圈 / 开关 / 档位 / 常用功能列表 |
| `MiDeviceWall` | `custom:mi-device-wall` | **动态区域墙**：拉设备树 + 区域标签栏 + 卡片网格（集成版主力） |
| `MiAreaWall` | — | 旧版静态区域墙，保留作对照；集成版不用它 |

注册方式：

```js
customElements.define("mi-device-card", MiDeviceCard);
customElements.define("mi-device-detail", MiDeviceDetail);
customElements.define("mi-device-wall", MiDeviceWall);
window.customCards = window.customCards || [];
window.customCards.push({ type: "custom:mi-device-wall", name: "米家设备墙", ... });
```

---

## 二、MiDeviceWall（动态区域墙）

### 数据获取

```js
const tree = await hass.callWS({ type: "mi_cards/device_tree" });
```

### 实时更新

```js
hass.connection.subscribeMessage(
  (msg) => this._rebuild(msg),
  { type: "subscribe_events", event_type: "mi_cards/tree_updated" }
);
```

外加 **120 秒兜底轮询**（防止事件丢失）。

### 网格布局

```css
.mi-grid {
  display: grid;
  gap: 16px;
  align-items: start;
  justify-content: center;
  grid-template-columns: repeat(auto-fill, var(--mi-card-w, 260px));
}
.mi-grid > mi-device-card { min-width: 0; aspect-ratio: 1.43 / 1; }
```

### 响应式断点（v1.0.1 修复的重点）

| 视口 | 布局 | 实现 |
| --- | --- | --- |
| > 900px | 固定 260px 卡片，自动填充列数 | `repeat(auto-fill, var(--mi-card-w, 260px))` |
| 620–900px | 固定 210px 卡片 | 媒体查询覆盖 `--mi-card-w` |
| ≤ 620px | **双列铺满容器宽度** | `repeat(var(--mi-mobile-cols, 2), minmax(0, 1fr))` |

> ⚠️ **v1.0.0 的 bug**：集成版 `DEVICE_WALL_CSS` 漏了移动端媒体查询
> （旧版 `MiAreaWall` 有），网格在所有宽度下都是 `repeat(auto-fill, 260px)`，
> 手机 App 上单列 + 右侧空 114px。v1.0.1 补齐。

### 配置项

```yaml
type: custom:mi-device-wall
accent: "#ff6a00"       # 主色
columns: 260            # 桌面卡片宽（px）
mobile_columns: 2       # 手机端列数
show_tabs: true         # 内部区域标签栏
show_area: true         # 副标题显示「区域 | 状态」
area: living_room       # 限定区域
```

`accent` / `columns` / `mobile_columns` 通过 CSS 变量注入到容器 style 上：

```js
this._box.style.setProperty("--mi-accent", accent);
this._box.style.setProperty("--mi-card-w", (Number(cfg.columns) || 260) + "px");
this._box.style.setProperty("--mi-mobile-cols", String(Number(cfg.mobile_columns) || 2));
```

---

## 三、卡片尺寸自适应：`cqh` 等比缩放

卡片内部所有尺寸都用 **`cqh`（容器查询高度单位）**，不是固定 px：

```css
@supports (height: 1cqh) {
  .mi-name { font-size: 4.2cqh; }
  .mi-sub  { font-size: 3.4cqh; }
  .mi-btn  { width: 12cqh; height: 12cqh; }
}
```

卡片自身 `aspect-ratio: 1.43 / 1`，容器高度变了 → `cqh` 变 → 内部元素等比缩放。
**这就是窄列下不需要额外适配的原因** —— 双列时卡片变矮，字号、按钮、图片自动等比缩小。

不支持 `cqh` 的旧浏览器会回落到 px 兜底值。

---

## 四、卡片点击行为

```js
if (cfg.detail_path)        navigate(cfg.detail_path);
else if (cfg.open_detail && cfg.device_id)
                             fireEvent(this, "mi-card-detail", { deviceId: cfg.device_id });
else if (cfg.entity)        fireEvent(this, "hass-more-info", { entityId: cfg.entity });
```

优先级：**指定路径 > 集成详情浮层 > HA 原生 more-info**。

`MiDeviceDetail` 收到 `mi-card-detail` 事件后弹出浮层；关闭时：

```js
if (cfg.close_on_back) fireEvent(this, "mi-detail-close", {});
```

### 详情浮层的实现细节

- **浮层挂到 `document.body`**，`position: fixed` —— 不受卡片容器 overflow 影响
- 关闭方式：ESC / 点击遮罩 / 返回按钮
- **浮层是内联样式，没有类名** —— 调试时要用
  `document.querySelector("mi-device-detail")` 定位，不能用 `.mi-overlay` 这类选择器

---

## 五、圆形按钮

```css
.mi-btn {
  position: absolute;
  top: 4cqh; right: 4cqh;
  width: 12cqh; height: 12cqh;
  border-radius: 50%;
  background: var(--mi-card-bg);
}
```

- 关闭态：灰色 + `mdi:power` 图标
- 开启态：`--mi-accent` 点亮
- 扫地机：`mdi:power` → `mdi:broom`（按设备类型切换图标）

---

## 六、CSS 变量清单

| 变量 | 作用 | 注入方 |
| --- | --- | --- |
| `--mi-accent` | 主色 | 卡片配置 `accent` |
| `--mi-accent-soft` | 主色的浅色变体 | 由 `--mi-accent` 派生 |
| `--mi-card-bg` | 卡片背景 | 样式表常量 |
| `--mi-gauge-bg` | 温度圈底色 | 样式表常量 |
| `--mi-card-w` | 桌面卡片宽度 | 卡片配置 `columns` |
| `--mi-mobile-cols` | 手机端列数 | 卡片配置 `mobile_columns` |

---

## 七、修改前端的注意事项

| # | 事项 |
| --- | --- |
| 1 | **改完必须 bump `const.py` 的 `VERSION`**，同时同步 `manifest.json` 的 `version`。资源 URL 是 `?v={VERSION}`，不 bump 浏览器拿旧文件 |
| 2 | 改完跑 `python3 tools/sync_release.py` 同步 HACS 镜像 |
| 3 | 用 `node --check mi-cards.js` 做语法检查 |
| 4 | 保持**零依赖** —— 不引入 npm 包、不用 lit、不需要构建步骤 |
| 5 | 内部尺寸优先用 `cqh`，避免写死 px（否则窄列会挤爆） |
| 6 | 新增媒体查询时**三个断点都要覆盖**（900 / 620 / 默认），别只改一个 |
| 7 | 保持 1.43:1 比例 —— `aspect-ratio: 1.43 / 1` 是产品视觉的一部分 |

---

## 八、与 legacy 版的关系

legacy 方案里的 `mi-cards.js`（1091 行）是本文件的前身，
只有 `custom:mi-device-card` 和 `custom:mi-device-detail` 两个元素。
集成版新增了 `custom:mi-device-wall`（动态区域墙，依赖 WS 拉取设备树）。

两者共享：卡片样式、详情浮层、圆形按钮、`cqh` 自适应方案。
差异只在「卡片数据从哪来」：legacy 是生成好的静态 YAML，集成版是运行时 WS 拉取。
