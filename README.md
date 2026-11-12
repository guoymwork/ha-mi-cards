# 米家风格设备面板（Mi Home Style Device Panel）

把米家 App 那种「一个设备一张横向卡片」的桌面搬进 Home Assistant，
而且**不需要任何外部机器** —— 设备树、产品图、面板生成全部在 HA 进程内完成。

```
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│   实物图      │  │   实物图      │  │   实物图      │
│        ⏻     │  │        ⏻     │  │        ⏻     │
│ 厨房·小厨宝   │  │ 客厅·空调     │  │  主卧·扫地机   │
│ 保温中        │  │ 制冷中        │  │ 清扫中        │
└──────────────┘  └──────────────┘  └──────────────┘
```

## 特性

- **1.43:1 横向卡片**，右上角圆形按钮随设备状态点亮（扫地机自动变成 🧹 小扫把）
- **实物图优先**：从米家产品百科抓官方产品图，统一裁切归一化（主体长边占 86%）
- **点击卡片**弹出设备详情：温度圈、开关、档位选择、常用功能列表
- **区域分类**放在 HA 原生顶部二级菜单（一个房间一个 view）
- **全屋视图**显示「区域 | 状态」，**区域视图**只显示状态
- **房间/设备增减改名自动适配** —— 注册表一变，前端立刻重建，不需要改任何配置
- **零配置**：装好即用，不需要 SSH、不需要令牌、不需要定时任务

## 安装

### HACS（推荐）

1. 在 HACS 里添加自定义仓库 `https://github.com/guoymwork/ha-mi-cards`
2. 分类选「仪表盘」，搜索「米家风格设备面板」
3. 下载后 **重启 Home Assistant**
4. 前往「设置 → 设备与服务」，点击右上角「添加集成」，搜索「米家风格设备面板」
5. 按提示确认面板路径（默认 `device-cards`）与主色（默认 `#ff6a00`）
6. 侧边栏会出现「设备」面板

### 手动安装

把 `custom_components/mi_cards` 整个目录拷到 HA 的 `config/custom_components/` 下，重启即可。

也可以从 [Releases](https://github.com/guoymwork/ha-mi-cards/releases) 下载 `mi_cards.zip`
（内容就是 `custom_components/mi_cards/`），解压到 `config/custom_components/` 下。

## 配置项

| 选项 | 默认值 | 说明 |
| --- | --- | --- |
| 面板路径 | `device-cards` | 面板 URL 路径，必须含连字符 `-` |
| 面板标题 | `设备` | 侧边栏显示的名字 |
| 主色 | `#ff6a00` | 卡片强调色，`#RRGGBB` |
| 在侧边栏显示 | 是 | 关掉则只保留 URL 访问 |
| 自动补齐产品图 | 是 | 开机后自动抓取缺失的实物图 |

改完点「配置」即可，面板会自动重建。

## 卡片

装好集成后，`custom:mi-device-wall` 卡片可以直接在任何面板里用：

```yaml
type: custom:mi-device-wall
title: 我的家          # 可选
accent: "#ff6a00"      # 可选
columns: 260           # 卡片宽度（px），默认 260
show_tabs: true        # 内部区域标签栏，默认 true
show_area: true        # 卡片副标题是否显示「区域 | 状态」
area: living_room      # 限定某个区域（区域 id / 名称）
```

另外两个卡片类型也可以单独使用：

| 类型 | 用途 |
| --- | --- |
| `custom:mi-device-card` | 单张设备小卡片 |
| `custom:mi-device-detail` | 设备详情页 |
| `custom:mi-device-wall` | 动态设备墙（推荐，自动跟随注册表变化） |

## 服务

| 服务 | 说明 |
| --- | --- |
| `mi_cards.sync_images` | 抓取/标准化产品图。可指定 `models` 列表、`force: true` 强制重抓 |
| `mi_cards.refresh` | 重扫设备树并重新生成面板 |

## 工作原理

```
        ┌──────────────────────── HA 进程内 ────────────────────────┐
        │                                                          │
 集成注册表  →  device_tree.build_device_tree()  →  WebSocket 下发
  (实时)         读 entity/device/area 注册表        mi_cards/device_tree
        │                                                 │
        │                                                 ▼
        │                                    custom:mi-device-wall
        │                                    （订阅 mi_cards/tree_updated）
        │
        └──  images.ImageManager  →  米家百科 API  →  Pillow 标准化
                                     →  www/mi_cards/images/*.png
```

- 设备树**不落盘**，每次按需从注册表现算，房间/设备改名立刻生效
- 产品图缓存在 `config/www/mi_cards/images/`，原始图留在 `config/mi_cards/raw/`
- 面板是 Lovelace 存储模式，配置写在 `config/.storage/lovelace.device_cards`

## 兼容版本

HA `2024.11` 及以上（开发与验证环境为 `2026.11.1`）。

## 目录结构

```
custom_components/mi_cards/
├── __init__.py        集成入口：静态资源 / WS 命令 / 面板 / 服务
├── config_flow.py     配置流与选项流
├── const.py           常量
├── device_tree.py     设备树构建（读注册表）
├── images.py          产品图抓取与标准化
├── manifest.json      集成清单
├── services.yaml      服务定义
├── strings.json       配置流文案
├── translations/      多语言
└── static/
    └── mi-cards.js    前端卡片（设备卡 / 详情 / 动态墙）

legacy/                旧版外部脚本方案（已废弃，仅作参考）
dev/                   浏览器自动化调试脚本
```

## License

MIT
