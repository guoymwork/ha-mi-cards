# 方案 A：独立脚本方案（传统实现）

> 这是米家风格设备面板的**第一代实现**。所有逻辑跑在一台常驻电脑（或 NAS 上的 cron）上，
> 通过 WebSocket 拉取 HA 快照 → 本地生成 Lovelace 配置 → SSH/SCP 回传 → 破缓存。
>
> 本目录保留它有两个原因：
> 1. **对照基线** —— 集成方案（`../ha-integration/`）的每个设计决策都能在这里找到「为什么当初要这么做」；
> 2. **兜底通道** —— 集成方案遇到无法在 HA 进程内解决的场景（如抓取外部数据源、批量迁移历史面板）时，仍可回到这里。
>
> ⚠️ 新功能请优先在集成方案里实现，本目录只做维护。

---

## 1. 它长什么样

```
┌────────────── 常驻电脑（开发机 / NAS） ──────────────┐
│                                                       │
│  refresh_tokens.py ──► 拿 access_token（30 分钟有效）  │
│                                                       │
│  ssh fnos  cd /tmp/mi-cards                          │
│      │                                                │
│      ├─ pull_state.py ──► ha_states.json              │
│      │                   ha_registries.json           │
│      │                                                │
│      ├─ gen_dashboard.py ──► device_dashboard.json    │
│      │                     mi-missing-models.json     │
│      │                     mi-images.json              │
│      │                     mi-cards-state.json  ← 稳定 slug/icon 映射（跨版本持久） │
│      │                                                │
│      └─ deploy_device_dashboard.py ──► 写入 Lovelace 面板
│          bump_resource_version.py   ──► 资源 URL 加 ?v=时间戳，破 31 天缓存
│                                                       │
│  本地补图：fetch_raw_images.py（抓百科原图）            │
│            normalize_images.py（Pillow 归一化）        │
│            scp → NAS www/mi-images/                  │
│                                                       │
│  入口：./deploy.sh（6 步幂等流水线，可挂 cron）          │
└───────────────────────────────────────────────────────┘
```

## 2. 文件清单

### 主流程脚本

| 文件 | 行数 | 职责 |
| --- | --- | --- |
| `deploy.sh` | 59 | **唯一入口**。6 步流水线：刷令牌 → scp 脚本 → 拉快照 → 生成 → 补图 → 部署 → 校验 |
| `sync.py` | 231 | 阶段编排器。`--stage snapshot/generate/deploy/verify/all`，输出差分报告 |
| `ha_ws.py` | 131 | HA WebSocket 客户端，**纯标准库**（手写帧编解码），无第三方依赖 |
| `refresh_tokens.py` | 78 | 从 NAS `.storage/auth` 取 refresh_token → 换 access_token → 写前端 localStorage 格式 |
| `pull_state.py` | 68 | 拉全部实体状态 + 实体/设备/区域三个注册表，落盘为 JSON |
| `gen_dashboard.py` | 931 | **核心**。状态 + 注册表 → Lovelace 面板配置；含型号识别、卡片选主、离线设备区 |
| `sync_state.py` | 406 | **稳定标识状态层**。区域/设备 ID → URL slug + 图标 的持久映射 |
| `deploy_device_dashboard.py` | 81 | 把生成的配置写进 Lovelace 面板（通过 WS 调 lovelace 相关命令） |
| `normalize_images.py` | 141 | Pillow 归一化产品图：裁主体 → 等比缩放 → 居中放 480×480 透明画布 |
| `fetch_raw_images.py` | 189 | 从米家产品百科抓**原图**（标准化会破坏原图，必须先存原图） |
| `fetch_baike_image.py` | 158 | 单型号调试用：抓一张图看看 |
| `bump_resource_version.py` | 54 | 给 Lovelace 资源 URL 的 `?v=` 换新值，破除浏览器缓存 |

### 实验/测试脚本（保留作回归参考）

| 文件 | 说明 |
| --- | --- |
| `test_nav_structure.py` | 校验生成的面板视图结构（视图数、path 唯一性） |
| `test_rename_adapt.py` | 模拟房间/设备改名，验证 slug 稳定 |
| `test_real_rename.py` | 真机改名回归 |
| `try_section_width.py` | sections 布局宽度实验 |

## 3. 文件契约（这一节最关键）

所有中间产物都在 `$MI_WORK_DIR`（默认 `/tmp/mi-cards`）下，**阶段之间只靠这些文件通信**：

| 文件 | 生产者 | 消费者 | 内容 |
| --- | --- | --- | --- |
| `ha_token.txt` | `refresh_tokens.py` / `deploy.sh` | 所有需要访问 HA 的脚本 | access_token 纯文本 |
| `ha_states.json` | `pull_state.py` | `gen_dashboard.py` | `hass.states` 全量快照（list） |
| `ha_registries.json` | `pull_state.py` | `gen_dashboard.py` | `entity_registry` / `device_registry` / `area_registry` |
| `mi-cards-state.json` | `sync_state.py` | `gen_dashboard.py` | **稳定标识映射**（跨版本持久，见 `docs/STATE-MODEL.md`） |
| `mi-missing-models.json` | `gen_dashboard.py` | `fetch_raw_images.py` | 缺产品图的型号清单 |
| `mi-images.json` | `gen_dashboard.py` | `gen_dashboard.py` | 型号 → 实物图 URL |
| `device_dashboard.json` | `gen_dashboard.py` | `deploy_device_dashboard.py` | 最终 Lovelace 配置 |

`mi-cards-state.json` **不在** `$MI_WORK_DIR`，而在 `MI_STATE_FILE`（NAS 上持久化到 `/vol1/1000/docker/haos/.mi-cards/state.json`）——
这是唯一必须跨版本存活的状态文件，其余都是可重算的中间产物。

## 4. 环境变量

```bash
MI_WORK_DIR      工作目录（默认 /tmp/mi-cards）
MI_TOKEN_FILE    token 文件（默认 $MI_WORK_DIR/ha_token.txt）
MI_HA_HOST       HA 地址（默认 127.0.0.1）
MI_HA_PORT       HA 端口（默认 8123）
MI_WWW_DIR       HA 的 www 目录（默认 /config/www）
MI_IMG_DIRS      图片目录（逗号分隔）
MI_DASH_PATH     面板 URL path（默认 device-cards）
MI_STATE_FILE    稳定标识状态文件路径
MI_OVERRIDES     人工覆盖配置（区域图标/显示名）路径
MI_MISSING_FILE  缺图清单路径
MI_IMG_VER       图片版本号（破缓存）
MI_RESOURCE_NAME Lovelace 资源文件名（默认 mi-cards.js）
```

## 5. 运行

```bash
# 全流程（需要 ssh 别名 fnos 指向 NAS）
./deploy.sh

# 单阶段（需在 NAS 上、工作目录内有中间产物时）
ssh fnos "cd /tmp/mi-cards && MI_WORK_DIR=/tmp/mi-cards python3 sync.py --stage verify"
```

## 6. 已知脆弱点（也是集成方案要解决的问题）

| 脆弱点 | 后果 | 集成方案的解法 |
| --- | --- | --- |
| 常驻电脑必须开机 | 电脑休眠/断网 → 面板停止更新 | 跑在 HA 进程内，HA 在就一直在 |
| 令牌 30 分钟过期 | 长跑任务中途失效 → 静默失败 | 用 HA 自己的 `hass` 上下文，不需要令牌 |
| SSH/SCP 依赖 | 换 HA 主机要改脚本 | 完全不需要 |
| 快照是「某一刻」 | 生成期间设备变化 → 配置与实际不一致 | 实时读注册表，无快照窗口 |
| 破缓存靠改资源 URL | 改一次刷一次，容易忘 | 资源 URL 带 `?v={VERSION}`，版本号 bump 即失效 |
| 浏览器 31 天缓存 | 用户看到旧界面却以为没生效 | 同上 |
| 面板覆盖无保护 | 冲掉用户自建面板 | `_has_foreign_content()` 保护 |
| 抓图在本机 | 本机没外网/Pillow 就缺图 | 在 HA 内抓，失败可重试并区分「未收录/请求失败」 |

## 7. 延伸阅读

- `docs/ARCHITECTURE.md` —— 流水线逐阶段拆解、WS 协议、生成器内部逻辑
- `docs/STATE-MODEL.md` —— 稳定标识状态层的设计与数据结构
- `docs/ROADMAP.md` —— 若继续维护本方案，下一步做什么
- `ai.prompt` —— 给 AI agent 的上下文说明（**改代码前必读**）
