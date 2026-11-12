# 米家风格设备面板 · mi-cards

把小米智能家居那种「一个设备一张横向卡片」的桌面搬进 Home Assistant。

**HACS 一装即用** —— 不需要常驻电脑、不需要 SSH、不需要令牌、不需要定时任务。

---

## 特性

| 特性 | 说明 |
| --- | --- |
| **1.43:1 横向卡片** | 和米家 App 一致的比例，右上角**圆形按钮**随设备状态点亮（扫地机自动变成扫把） |
| **实物图优先** | 从米家产品百科抓官方产品图，裁切归一化后所有设备视觉大小一致 |
| **区域分类** | 放在 HA 原生**顶部二级菜单**，一个房间一个视图 |
| **双态副标题** | 全屋视图显示「客厅 \| 开启」，区域视图只显示「开启」 |
| **设备详情浮层** | 点卡片弹出：实物图 + 温度圈 + 开关 + 档位 + 常用功能列表 |
| **房间自适应** | 房间/设备增减改名自动适配，注册表一变前端立刻重建 |
| **手机双列** | 手机 App 上两列铺满，不再是难看的大片留白 |
| **零配置** | 装上 → 重启 → 添加集成，完事 |
| **零凭据** | 集成跑在 HA 进程内，不需要任何 token |

---

## 安装（HACS）

1. HACS → 侧边栏「自定义仓库」→ 添加 `https://github.com/guoymwork/ha-mi-cards`
2. 分类选「仪表盘」，搜索「米家风格设备面板」
3. 下载后 **重启 Home Assistant**
4. 设置 → 设备与服务 → 右上角「添加集成」→ 搜索「米家风格设备面板」
5. 确认面板路径（默认 `device-cards`）与主色（默认 `#ff6a00`）
6. 侧边栏出现「设备」面板

<details>
<summary>手动安装</summary>

下载 [Release](https://github.com/guoymwork/ha-mi-cards/releases) 里的
`mi_cards-<版本>.zip`，解压到 HA 的 `config/custom_components/` 下，重启。
</details>

---

## 卡片用法

集成会自动生成一个「设备」面板。也可以把卡片放进你自己建的任意 Lovelace 面板：

```yaml
type: custom:mi-device-wall
title: 我的家          # 可选
accent: "#ff6a00"      # 可选，主色
columns: 260           # 桌面卡片宽度（px），默认 260
mobile_columns: 2      # 手机端列数，默认 2
show_tabs: true        # 内部区域标签栏，默认 true
show_area: true        # 卡片副标题是否显示「区域 | 状态」
area: living_room      # 只显示某个区域（区域 id / 名称）
```

单张设备卡：

```yaml
type: custom:mi-device-card
entity: switch.living_room_lamp
```

---

## 配置项与服务

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `dashboard_url` | `device-cards` | 面板 URL 路径。**已被你自己的面板占用时，集成会跳过写入并保留你的配置** |
| `dashboard_title` | `设备` | 侧边栏与面板标题 |
| `accent` | `#ff6a00` | 主色 |
| `show_in_sidebar` | `true` | 是否在侧边栏显示 |
| `auto_sync_images` | `true` | 启动时自动补齐产品图 |

| 服务 | 参数 | 说明 |
| --- | --- | --- |
| `mi_cards.sync_images` | `force`(bool)、`models`(list) | 抓取/标准化产品图 |
| `mi_cards.refresh` | — | 重建设备树并重写面板 |

---

## 目录结构

```
ha-mi-cards/
├── ai.prompt                  ← ★ AI agent 上下文（先读这个）
├── hacs.json                 HACS 仓库元数据
├── custom_components/mi_cards/   ← 集成源码（HACS 直接安装这里）
│   ├── __init__.py           入口：静态资源 / WS 命令 / 面板 / 服务 / 注册表监听
│   ├── config_flow.py        配置流与选项流
│   ├── const.py              常量（域名、版本号、WS 类型、配置项名）
│   ├── device_tree.py        设备树构建（读三个注册表）
│   ├── images.py             产品图抓取与标准化
│   ├── manifest.json         集成清单
│   ├── services.yaml         服务定义
│   ├── strings.json          配置流文案
│   ├── translations/         en / zh-Hans
│   └── static/mi-cards.js    前端卡片（设备卡 / 详情浮层 / 动态区域墙）
│
├── docs/                     技术文档
│   ├── ARCHITECTURE.md       模块职责、生命周期、面板与资源写入协议
│   ├── HA-API-FACTS.md       ★ 已核验的 HA API 事实表（所有踩过的坑）
│   ├── FRONTEND.md           前端卡片体系、样式、响应式
│   ├── TESTING.md            验证工作流与验收清单
│   └── ROADMAP.md            扩展路线图（下一步技术路线）
│
├── dev/                      CDP 浏览器调试脚本（开发者用）
└── tools/
    ├── check.py              仓库自检（结构 / manifest / 敏感信息 / 版本一致性）
    ├── install_git_hooks.sh  安装本地守卫钩子
    ├── enable_ci.sh          启用 GitHub Actions（需 workflow scope）
    └── github-actions/ci.yml CI 配置
```

---

## 开发

```bash
# 仓库自检（结构 / manifest 规范 / 敏感信息 / 版本一致性 / 语法）
python3 tools/check.py

# 安装本地守卫钩子：提交前自动跑上面这些检查
bash tools/install_git_hooks.sh
```

**改动前必读** [`ai.prompt`](ai.prompt)（给 AI agent 的上下文）与
[`docs/HA-API-FACTS.md`](docs/HA-API-FACTS.md)（已核验的 HA API 行为）。
改完按 [`docs/TESTING.md`](docs/TESTING.md) 的验收清单过一遍。

### 发布

```bash
# 1. 改完前端 JS 后，bump 两处版本号
#    custom_components/mi_cards/const.py     -> VERSION = "1.x.y"
#    custom_components/mi_cards/manifest.json -> "version": "1.x.y"
# 2. 打包（zip 里只有 custom_components/）
rm -rf /tmp/pkg && mkdir -p /tmp/pkg/custom_components
rsync -a --exclude '__pycache__' custom_components/mi_cards /tmp/pkg/custom_components/
(cd /tmp/pkg && zip -qr mi_cards-1.x.y.zip . -x '*.DS_Store')
# 3. 打 tag 发 Release
gh release create v1.x.y mi_cards-1.x.y.zip --title "v1.x.y" --notes "..."
```

> 版本号是前端资源的缓存键（资源 URL 带 `?v={VERSION}`）。不 bump 的话
> 浏览器拿旧文件，**改了等于没改**。

---

## 给 AI agent / 协作者

仓库根有一份 [`ai.prompt`](ai.prompt)，是为 AI agent 写的上下文说明：
项目背景、模块地图、**12 条硬性约束**、已核验的 HA API 行为速查、
常见任务的技术路线、验证流程。**开始改代码前请先读它。**

配套技术文档：

| 文档 | 内容 |
| --- | --- |
| [HA-API-FACTS.md](docs/HA-API-FACTS.md) | ★ 已核验的 HA API 事实表（`probatio` / `Store` / `LovelaceStorage` / 弃用项…） |
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | 集成架构、生命周期、面板写入协议 |
| [FRONTEND.md](docs/FRONTEND.md) | 前端卡片体系、响应式断点 |
| [TESTING.md](docs/TESTING.md) | 验证工作流与验收清单 |
| [ROADMAP.md](docs/ROADMAP.md) | 扩展路线图（下一步技术路线） |

---

## 环境要求

- Home Assistant `2024.11.0` 及以上（开发验证于 `2026.11.1`）
- **无第三方依赖** —— Pillow / probatio / aiohttp 都是 HA 核心自带

## 前代方案

本项目最早是「独立脚本 + SSH 部署」的实现（常驻电脑 + 令牌 + 定时任务），
已被本仓库完全取代。那套代码保留在
[ha-mi-cards-legacy](https://github.com/guoymwork/ha-mi-cards-legacy)（**已归档废弃**），
仅作设计参考与兜底通道。

## License

MIT —— 见 [LICENSE](LICENSE)。
