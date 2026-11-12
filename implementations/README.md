# 两套实现对照

同一个产品（米家风格设备面板）的两代实现。**产品特性一致，架构不同。**

| | `ha-integration/`（方案 B） | `legacy-standalone/`（方案 A） |
| --- | --- | --- |
| **形态** | HA custom integration | 独立 Python 脚本 |
| **运行位置** | HA 进程内 | HA 之外的常驻电脑 / NAS cron |
| **安装** | HACS → 重启 → 添加集成 | scp 脚本 + 配令牌 + 挂定时任务 |
| **凭据** | **零**（用 `hass` 上下文） | access_token（30 分钟过期）+ NAS SSH |
| **数据来源** | 实时读三个注册表 | WS 拉快照 → 落盘 JSON |
| **更新触发** | 注册表事件 → 事件总线 → 前端重建 | cron 周期 |
| **房间改名** | `area_id` 不变 → 天然稳定 | 需自建 `SyncState` 状态层维持 |
| **产品图** | 集成内抓（`images.py`） | 本机抓（`fetch_raw_images.py`） |
| **破缓存** | `?v={VERSION}` 语义化版本 | `?v={时间戳}` |
| **用户配置保护** | 有（`_has_foreign_content()`） | 无（直接覆盖） |
| **依赖** | 无第三方（Pillow/probatio/aiohttp 都是 HA 核心自带） | Pillow + 标准库 |
| **分发** | HACS 商店 | 拷贝脚本 |
| **状态** | **主方案** | 历史方案，只做维护 |

---

## 目录内容

### `ha-integration/` —— 方案 B（主）

```
ai.prompt                    ← AI agent 上下文
README.md                    ← 文件清单、配置项、卡片用法
custom_components/mi_cards/  ← 源码真身
dev/                         ← CDP 浏览器调试脚本
docs/
  ARCHITECTURE.md            模块职责、生命周期、面板与资源写入协议
  HA-API-FACTS.md            ★ 已核验的 HA API 事实表（所有踩过的坑）
  FRONTEND.md                前端卡片体系、样式、响应式
  TESTING.md                 验证工作流与验收清单
  ROADMAP.md                 扩展路线图
```

### `legacy-standalone/` —— 方案 A（历史）

```
ai.prompt                    ← AI agent 上下文
README.md                    ← 文件清单、文件契约表
docs/
  ARCHITECTURE.md            6 步流水线逐阶段拆解、WS 协议
  STATE-MODEL.md             ★ 稳定标识状态层的设计
  ROADMAP.md                 维护路线图
*.py / *.sh                  脚本本体（2864 行）
```

---

## 共同的产品特性

两套实现产出的界面**几乎一致**：

- 1.43:1 横向卡片，右上角圆形按钮随状态点亮（扫地机按钮是扫把）
- 实物图优先（米家产品百科）
- 区域分类放在 HA 原生顶部二级菜单
- 全屋视图显示「区域 \| 状态」，区域视图只显示状态
- 点击卡片进入设备详情（温度圈 / 开关 / 档位 / 常用功能）
- 手机端双列（v1.0.1 修复）

图片归一化的 5 个常量（`CANVAS=480 FILL=0.86 WIDE_RATIO=2.0 WIDE_FILL=0.92 MIN_CONTENT=12`）
在两套实现里**完全相同**，保证图片观感一致。

---

## 为什么保留 legacy

1. **对照基线** —— 集成方案的每个设计决策都能在这里找到「为什么当初要这么做」。
   最典型的是 `sync_state.py` 揭示的「用可变显示名当不可变标识」的坑，
   而集成方案正是靠 HA 原生的 `area_id` + `area.icon` 绕开了它。
2. **兜底通道** —— 集成方案解决不了的场景（如批量迁移历史面板）仍可回到这里。
3. **知识留存** —— 手写 WS 客户端、原子写状态、两段式图片流水线的实现细节值得留着。

---

## 迁移对照（如果你在把 legacy 的逻辑搬到集成里）

| legacy 做的事 | 集成里的对应物 |
| --- | --- |
| `pull_state.py` 拉快照 | `device_tree.py` 直接读注册表 |
| `gen_dashboard.py` 生成视图 | `__init__.py::_build_dashboard_config()` |
| `sync_state.py` 稳定 slug | HA 原生 `area_id` + `area.icon`（可选持久化见 ROADMAP #1） |
| `fetch_raw_images.py` + `normalize_images.py` | `images.py::ImageManager.async_sync()` |
| `deploy_device_dashboard.py` | `LovelaceStorage.async_save()` |
| `bump_resource_version.py` | `?v={VERSION}` |
| `ha_ws.py` + `refresh_tokens.py` | **不需要** —— 集成在 HA 进程内 |
| `deploy.sh` 6 步流水线 | HA 生命周期 + 注册表事件 |
