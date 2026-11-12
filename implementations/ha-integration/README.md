# 方案 B：Home Assistant 集成（当前主方案）

把米家 App 那种「一个设备一张横向卡片」的桌面搬进 Home Assistant，
**不需要任何常驻电脑、不需要 SSH、不需要令牌、不需要定时任务**。

装好即用：HACS 装 → 重启 → 添加集成 → 侧边栏出现「设备」面板。

---

## 1. 它长什么样

```
                    ┌────────── Home Assistant 进程内 ──────────┐
                    │                                           │
 区域/设备变化 ────► │  注册表监听（area/device/entity registry）  │
                    │        │                                  │
                    │        ▼                                  │
                    │  device_tree.build_device_tree()           │
                    │   ├─ 区域列表（id/name/slug/icon）         │
                    │   ├─ 每设备：主实体/开关/状态/详情行        │
                    │   └─ 30s 缓存，注册表变化立即失效          │
                    │        │                                  │
                    │        ├──► WS 命令 mi_cards/device_tree   │──► 前端
                    │        │                                  │    custom:mi-device-wall
                    │        ├──► 事件 mi_cards/tree_updated     │◄── 订阅后自动重建
                    │        │                                  │
                    │        └──► images.ImageManager            │
                    │             抓米家百科 → Pillow 归一       │
                    │             → <config>/www/mi_cards/images/│
                    │                                           │
                    │  Lovelace 面板（存储模式）                 │
                    │   全部视图 + 每个区域一个视图                │
                    └───────────────────────────────────────────┘
```

## 2. 目录结构

```
implementations/ha-integration/
├── ai.prompt                     ← AI agent 上下文（改代码前必读）
├── README.md                     ← 本文件
├── custom_components/mi_cards/   ← 源码真身（改这里）
│   ├── __init__.py               集成入口：静态资源 / WS 命令 / 面板 / 服务 / 注册表监听
│   ├── config_flow.py            配置流与选项流
│   ├── const.py                  常量（域名、版本号、WS 类型、配置项名）
│   ├── device_tree.py            设备树构建（读三个注册表）
│   ├── images.py                 产品图抓取与标准化
│   ├── manifest.json             HA 集成清单
│   ├── services.yaml             服务定义
│   ├── strings.json              配置流文案
│   ├── translations/             en / zh-Hans
│   └── static/mi-cards.js        前端卡片（设备卡 / 详情浮层 / 动态区域墙）
├── dev/                          CDP 浏览器调试脚本（真机截图与布局断言）
└── docs/
    ├── ARCHITECTURE.md           模块职责、生命周期、面板与资源写入协议
    ├── HA-API-FACTS.md           ★ 已核验的 HA API 事实表（所有踩过的坑）
    ├── FRONTEND.md               前端卡片体系、样式、响应式、WS 协议
    ├── TESTING.md                本地与真机验证工作流
    └── ROADMAP.md                扩展路线图（下一步技术路线）
```

> **源码真身 vs HACS 发布镜像**
>
> HACS 硬性要求集成代码位于仓库根的 `custom_components/<domain>/`。
> 本仓库把实现放进 `implementations/ha-integration/` 以便与独立脚本方案并列，
> 因此根目录的 `custom_components/mi_cards/` 是**由脚本生成的发布镜像**：
>
> ```bash
> python3 tools/sync_release.py          # 同步
> python3 tools/check_release.py        # 校验一致（CI 强制）
> ```
>
> **改代码请改 `implementations/ha-integration/custom_components/mi_cards/`**，
> 然后跑一次 `sync_release.py`。直接改根目录镜像会在 CI 里被判为漂移。

## 3. 安装（HACS）

1. HACS → 添加自定义仓库 `https://github.com/guoymwork/ha-mi-cards`
2. 分类选「仪表盘」，搜索「米家风格设备面板」
3. 下载后 **重启 Home Assistant**
4. 设置 → 设备与服务 → 添加集成 → 搜索「米家风格设备面板」
5. 确认面板路径（默认 `device-cards`）与主色（默认 `#ff6a00`）
6. 侧边栏出现「设备」面板

手动安装：把 `custom_components/mi_cards/` 拷到 HA 的 `config/custom_components/` 下，重启。

## 4. 配置项

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `dashboard_url` | `device-cards` | 面板 URL 路径。**若该路径已被你自己的面板占用，集成会跳过写入并打警告，不会冲掉你的配置** |
| `dashboard_title` | `设备` | 侧边栏与面板标题 |
| `accent` | `#ff6a00` | 主色（橙色系） |
| `show_in_sidebar` | `true` | 是否在侧边栏显示 |
| `auto_sync_images` | `true` | 启动时自动补齐产品图 |

## 5. 服务

| 服务 | 参数 | 说明 |
| --- | --- | --- |
| `mi_cards.sync_images` | `force`(bool)、`models`(string list) | 抓取/标准化产品图。`force=true` 强制重抓 |
| `mi_cards.refresh` | — | 重建设备树并重写面板 |

```yaml
# yaml 自动化
action: mi_cards.sync_images
data:
  force: false
```

## 6. 卡片（可放进任意 Lovelace 面板）

```yaml
type: custom:mi-device-wall
title: 我的家          # 可选
accent: "#ff6a00"      # 可选
columns: 260           # 桌面卡片宽度（px），默认 260
mobile_columns: 2      # 手机端列数，默认 2
show_tabs: true        # 内部区域标签栏，默认 true
show_area: true        # 卡片副标题是否显示「区域 | 状态」
area: living_room      # 限定某个区域（区域 id / 名称）
```

也可以直接用单张设备卡：

```yaml
type: custom:mi-device-card
entity: switch.living_room_lamp
```

## 7. 产品特性

| 特性 | 实现位置 |
| --- | --- |
| 1.43:1 横向卡片 | 前端 `aspect-ratio: 1.43 / 1` |
| 右上角圆形按钮随状态点亮 | `mi-device-card` 的 `.mi-btn` |
| 实物图优先（米家产品百科） | `images.py::ImageManager` |
| 区域分类放 HA 原生顶部二级菜单 | 面板用「一个区域一个 view」实现 |
| 全屋视图显示「区域 \| 状态」，区域视图只显示状态 | `show_area` 随视图切换 |
| 点击卡片进入设备详情 | `mi-device-detail` 浮层 |
| 房间/设备变化自适应 | 注册表事件 → 重建面板 + 广播 `tree_updated` |
| 朋友零配置部署 | HACS 安装 + 添加集成 |

## 8. 延伸阅读

- `ai.prompt` —— **AI agent 上下文，开工前必读**
- `docs/ARCHITECTURE.md` —— 模块职责与生命周期
- `docs/HA-API-FACTS.md` —— ★ 已核验的 HA API 事实（`probatio` / `Store` / `LovelaceStorage` / 弃用项…）
- `docs/FRONTEND.md` —— 前端卡片与样式体系
- `docs/TESTING.md` —— 真机验证工作流（NAS 环境、CDP 调试脚本）
- `docs/ROADMAP.md` —— 下一步技术路线
