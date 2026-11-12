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

## 仓库里有两套实现

同一产品的两代实现，**产品特性一致**，架构不同。

| | `implementations/ha-integration/` | `implementations/legacy-standalone/` |
| --- | --- | --- |
| 形态 | HA custom integration | 独立 Python 脚本 |
| 运行位置 | HA 进程内 | HA 之外的常驻电脑 / NAS cron |
| 凭据 | **零** | access_token + NAS SSH |
| 更新触发 | 注册表事件实时重建 | cron 周期 |
| 房间改名 | `area_id` 不变，天然稳定 | 需自建状态层维持 |
| 用户配置保护 | 有 | 无 |
| 状态 | **主方案** | 历史方案，只做维护 |

完整对照表见 [`implementations/README.md`](implementations/README.md)。

---

## 目录结构

```
ha-mi-cards/
├── ai.prompt                  ← AI agent 仓库总纲（先读这个）
├── hacs.json                 HACS 仓库元数据
├── custom_components/mi_cards/  ← HACS 发布镜像（脚本生成，勿手改）
│
├── tools/
│   ├── sync_release.py       同步镜像：implementations/ → 仓库根
│   └── check_release.py      校验镜像一致（CI 强制）
│
└── implementations/
    ├── README.md             两套方案对照
    ├── ha-integration/       ← 方案 B（主）
    │   ├── ai.prompt
    │   ├── custom_components/mi_cards/   源码真身
    │   ├── dev/               CDP 浏览器调试脚本
    │   └── docs/              架构 / HA API 事实 / 前端 / 测试 / 路线图
    └── legacy-standalone/    ← 方案 A（历史）
        ├── ai.prompt
        ├── docs/              架构 / 状态模型 / 路线图
        └── *.py *.sh          脚本本体
```

### 源码真身 vs 发布镜像

HACS 要求集成代码在仓库根的 `custom_components/`，而本仓库把实现放进
`implementations/ha-integration/` 以便两套方案并列。因此根目录那份是**生成的镜像**：

```bash
python3 tools/sync_release.py          # 同步
python3 tools/check_release.py        # 校验一致（CI 强制）
```

**改代码请改 `implementations/ha-integration/custom_components/mi_cards/`。**

---

## 给 AI agent / 协作者

仓库里每个方案都带一份 `ai.prompt`，是为 AI agent 写的上下文说明：

| 文件 | 内容 |
| --- | --- |
| [`ai.prompt`](ai.prompt) | 仓库总纲：两套方案怎么选、发布镜像机制、硬性约定 |
| [`implementations/ha-integration/ai.prompt`](implementations/ha-integration/ai.prompt) | 集成方案：模块地图、**12 条硬性约束**、常见任务的技术路线 |
| [`implementations/legacy-standalone/ai.prompt`](implementations/legacy-standalone/ai.prompt) | 脚本方案：流水线拆解、文件契约、已知脆弱点 |

配套技术文档：

| 文档 | 内容 |
| --- | --- |
| [HA-API-FACTS.md](implementations/ha-integration/docs/HA-API-FACTS.md) | ★ 已核验的 HA API 事实表（`probatio` / `Store` / `LovelaceStorage` / 弃用项…） |
| [ARCHITECTURE.md](implementations/ha-integration/docs/ARCHITECTURE.md) | 集成架构、生命周期、面板写入协议 |
| [FRONTEND.md](implementations/ha-integration/docs/FRONTEND.md) | 前端卡片体系、响应式断点 |
| [TESTING.md](implementations/ha-integration/docs/TESTING.md) | 真机验证工作流与验收清单 |
| [ROADMAP.md](implementations/ha-integration/docs/ROADMAP.md) | 扩展路线图（下一步技术路线） |
| [STATE-MODEL.md](implementations/legacy-standalone/docs/STATE-MODEL.md) | 稳定标识状态层的设计由来 |

---

## 环境要求

- Home Assistant `2024.11.0` 及以上（开发验证于 `2026.11.1`）
- **无第三方依赖** —— Pillow / probatio / aiohttp 都是 HA 核心自带

## License

MIT —— 见 [LICENSE](LICENSE)。
