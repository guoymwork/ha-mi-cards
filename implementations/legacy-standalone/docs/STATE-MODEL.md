# 稳定标识状态层（`sync_state.py`）

> 本文解释一个看起来多余、但删掉就会出线上事故的模块。

---

## 一、它解决什么问题

HA 内部有两个「永远不会变」的标识：

- `area_id` —— 区域（房间）的内部 ID
- `device_id` —— 设备的内部 ID

但我们最初是用**中文房间名**和**设备名**去推导 URL path 和图标：

```python
slug = slugify("客厅")          # -> "living"
icon = guess_icon("客厅")        # -> "mdi:sofa"
```

一旦用户把「客厅」改名为「起居室」，就会连锁出三个问题：

| 问题 | 表现 |
| --- | --- |
| URL 变了 | 收藏的 `/device-cards/living` 直接 404 |
| 图标掉了 | 「起居室」不在映射表里 → 回退成 `mdi:home-outline` |
| 位置乱了 | 用户手动排的卡片顺序错位 |

**根因**：用「可变的显示名」当「不可变的标识」。

---

## 二、解法

把推导结果**持久化**，用不可变 ID 当 key：

```json
{
  "version": 2,
  "areas": {
    "<area_id>":   { "slug": "living", "icon": "mdi:sofa", "title": "客厅" },
    "<area_id_2>": { "slug": "master-bedroom", "icon": "mdi:bed-king-outline", "title": "主卧" }
  },
  "devices": {
    "<device_id>": { "slug": "xiao-ai-yin-xiang", "title": "小爱音箱Pro" }
  }
}
```

文件位置：`MI_STATE_FILE`（NAS 上默认 `/vol1/1000/docker/haos/.mi-cards/state.json`）。
**必须跨版本存活**，所以它不在 `$MI_WORK_DIR`（可重算的临时目录）里。

---

## 三、slug 推导优先级

`SyncState._pick_area_slug(area_id, name)`：

```
1. 旧版迁移表 LEGACY_AREA_PATH   （中文名硬编码，仅首次迁移用）
        ↓ 保证升级前的收藏链接继续有效
2. area_id 派生 slug_from_area_id()（小米生态集成自动建的 area_id 本身就是拼音）
        ↓ ke_ting -> "ke-ting"
3. 名称推断 guess_area_slug_and_icon()（走 ROOM_TABLE 中文名映射表）
        ↓ "客厅" -> "living" + "mdi:sofa"
4. 哈希兜底 "room-" + _stable_hash(key)   （自建区域是 UUID，无语义）
```

### 为什么第 2 步能work

小米生态集成自动创建区域时，`area_id` 直接就是拼音短名（`ke_ting` / `yu_shi`），
本身就是理想的 URL 片段。而用户在 UI 里自建的区域，`area_id` 是 UUID，没有语义 → 走第 3/4 步。

`UUID_RE` 用来区分这两者：

```python
UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-")
```

### ROOM_TABLE 的顺序敏感

匹配策略是「先整名精确匹配，再按表顺序做包含匹配」。**包含匹配时顺序至关重要** ——
「主卧」必须在「卧室」之前命中，否则「主卧」会被解析成 `bedroom`。

```python
ROOM_TABLE = [
    ("主卧", "master-bedroom", "mdi:bed-king-outline"),   # 必须在 "卧室" 之前
    ("次卧", "second-bedroom", "mdi:bed-outline"),
    ("卧室", "bedroom", "mdi:bed-outline"),
    ...
]
```

---

## 四、改名行为约定

| 场景 | slug | icon | title |
| --- | --- | --- | --- |
| 房间改名 | **沿用旧记录** | 沿用旧记录（除非旧 icon 是自动推断且新名能推断出更好的） | 跟随新名 |
| 设备改名 | **沿用旧记录** | — | 跟随新名 |
| 新增房间 | 按上表推断 | 按上表推断 | 新名 |
| 删除房间 | 记录保留（房间重建时可复用 slug） | — | — |
| 离线设备区 | 固定 key `__offline__`，slug 固定 `offline` | `mdi:cloud-off-outline` | 「离线设备」 |

### 图标来源标记

`_infer_icon_with_src()` 会记录图标是「整名命中」还是「包含匹配」推断出来的。
这个来源标记决定了**改名后要不要重新推断图标**：

- 来源是「整名命中」→ 改名后重新推断（用户明显换了个房间，图标该跟着变）
- 来源是「包含匹配」/「哈希兜底」→ 沿用旧图标（避免把精心设置的图标冲掉）

---

## 五、人工覆盖（overrides）

用户可能想自己指定图标或显示名。`mi-overrides.json`（放在 state.json 同目录，或 `MI_OVERRIDES` 指定）：

```json
{
  "areas": {
    "<area_id>": { "slug": "living", "icon": "mdi:sofa", "title": "客厅" }
  },
  "areas_by_name": {
    "客厅": { "icon": "mdi:tv" }
  },
  "devices": {
    "<device_id>": { "title": "客厅小爱" }
  }
}
```

查找顺序：显式参数 > `MI_OVERRIDES` 环境变量 > state.json 同目录的 `mi-overrides.json`。
`areas_by_name` 是给「还没建区域、只有名字」的场景用的（按 ID 覆盖优先于按名覆盖）。

---

## 六、`prune()` 与 `report()`

- `prune(live_area_ids, live_device_ids)` —— 清理已不存在的记录，但**保留 area 的记录**
  （房间删了又建，slug 能复用，避免 URL 漂移）。device 记录会被清理。
- `report()` —— 返回本次运行的变更摘要（新增/移除/改名的房间与设备），
  `sync.py` 的 `--stage generate` 会把它打成差分报告。

---

## 七、`SyncState` 公共方法

```python
SyncState(path, overrides_path=None)
    .area(area_id, name)          -> {"slug": ..., "icon": ..., "title": ...}
    .device(device_id, name)      -> {"slug": ..., "title": ...}
    .prune(live_area_ids, live_device_ids)
    .report()
    .save()                        # 原子写：先写 .tmp 再 os.replace
    .changes                       # 变更摘要列表
```

`.save()` 用「临时文件 + `os.replace`」做原子替换，避免进程被杀时留下半截 JSON。

---

## 八、集成方案为什么不需要这个模块

集成方案（`../ha-integration/`）里，区域 slug 直接由 `area_id` 现场推导，不落盘状态：

- `device_tree.py` 每次现算，区域 id → slug 的映射是纯函数
- 区域改名 → `area_id` 不变 → slug 不变（**天然稳定**）
- 图标改成从**区域的 `icon` 属性**直接读（HA 原生就有区域图标字段），而不是靠中文名猜

也就是说，HA 原生的 `area_id` + `area.icon` 已经提供了「稳定标识 + 用户可控图标」，
独立脚本方案缺这个能力，才需要自建状态层来补。

**但集成方案仍有残留**：如果区域 id 是 UUID（用户自建），slug 就不够稳定。
这是集成方案后续可改进的点（见 `../ha-integration/docs/ROADMAP.md`）。
