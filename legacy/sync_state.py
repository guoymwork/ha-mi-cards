#!/usr/bin/env python3
"""稳定标识状态层：让面板在房间/设备增删改名后保持 URL 与图标稳定。

核心思路
--------
HA 的 `area_id` / `device_id` 是内部 UUID，一旦创建就不会变；
而我们之前用「中文房间名」「设备名」推导 URL path 与图标，
导致：房间改名 -> URL 变了（收藏的链接失效）、图标掉回默认。

本模块把推导结果持久化到 state.json，用稳定 ID 做 key：

    {
      "version": 1,
      "areas":   {"<area_id>":  {"slug": "living",  "icon": "mdi:sofa",  "title": "客厅"}},
      "devices": {"<device_id>":{"slug": "xiao-ai-yin-xiang", "title": "小爱音箱Pro"}}
    }

行为约定
--------
* 房间改名  -> slug / icon 沿用旧记录（除非旧 icon 是自动推断且新名能推断出更好的）
* 设备改名  -> slug 沿用旧记录，标题跟随新名
* 新增房间  -> 自动推断 slug + 图标
* 删除房间  -> 记录保留（万一房间被重建，slug 复用），但不再出现在面板
* 离线设备区 -> 固定 key "__offline__"，slug 固定 "offline"

用法:
    st = SyncState("/path/state.json")
    st.area(area_id, "客厅")   # -> {"slug": ..., "icon": ..., "title": ...}
    st.device(dev_id, "小爱音箱Pro")
    st.save()
    print(st.report())
"""
import hashlib
import json
import os
import re

STATE_VERSION = 2

# 兼容旧版按「中文房间名」硬编码的 path/icon —— 仅用于首次迁移，
# 让升级前的收藏链接（/device-cards/living 等）继续有效。
LEGACY_AREA_PATH = {
    "客厅": "living", "餐厅": "dining", "厨房": "kitchen", "卧室": "bedroom",
    "主卧": "master-bedroom", "次卧": "second-bedroom", "书房": "study",
    "浴室": "bathroom", "卫生间": "bathroom", "阳台": "balcony",
    "庭院": "courtyard", "院子": "yard", "车库": "garage",
    "门厅": "hallway", "玄关": "entrance", "智能插座": "sockets",
    "su7": "car", "离线设备": "offline", "其他设备": "others",
}
LEGACY_AREA_ICON = {
    "客厅": "mdi:sofa", "餐厅": "mdi:silverware-fork-knife",
    "厨房": "mdi:fridge-outline", "卧室": "mdi:bed-outline",
    "主卧": "mdi:bed-king-outline", "次卧": "mdi:bed-outline",
    "书房": "mdi:desk", "浴室": "mdi:shower", "卫生间": "mdi:shower",
    "阳台": "mdi:flower-outline", "庭院": "mdi:tree", "院子": "mdi:tree",
    "车库": "mdi:garage", "门厅": "mdi:door-open", "玄关": "mdi:door-open",
    "智能插座": "mdi:power-plug", "su7": "mdi:car",
    "离线设备": "mdi:cloud-off-outline", "其他设备": "mdi:dots-horizontal",
}

# 自建区域的 area_id 是 UUID；小米集成自动创建的 area_id 是拼音/英文短名。
UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-")


def slug_from_area_id(area_id):
    """由 area_id 派生稳定 slug。

    小米生态集成自动建区域时 area_id 就是拼音（ke_ting / yu_shi），
    本身就是理想的 URL 片段；自建区域是 UUID，没有语义，退回 None。
    """
    if not area_id:
        return None
    if UUID_RE.match(area_id):
        return None
    s = re.sub(r"[^a-zA-Z0-9_-]+", "-", area_id).strip("-").lower()
    if not s or len(s) > 24:      # 太长多半是随机 ID
        return None
    return s

# --------------------------------------------------------------------------
# 中文房间名 -> (英文 slug, mdi 图标)
#
# 匹配策略：先「整名精确匹配」，再「按表顺序做包含匹配」。
# 包含匹配时顺序很重要 —— 主卧必须在卧室之前命中。
# --------------------------------------------------------------------------
ROOM_TABLE = [
    # (关键词, slug, icon)
    ("主卧",       "master-bedroom",  "mdi:bed-king-outline"),
    ("次卧",       "second-bedroom",  "mdi:bed-outline"),
    ("儿童房",     "kids-room",       "mdi:baby-face-outline"),
    ("老人房",     "elder-room",      "mdi:human-male-female-child"),
    ("婴儿房",     "nursery",         "mdi:baby"),
    ("卧室",       "bedroom",         "mdi:bed-outline"),
    ("主卧房",     "master-bedroom",  "mdi:bed-king-outline"),
    ("客房",       "guest-room",      "mdi:bed-outline"),
    ("起居室",     "living",          "mdi:sofa"),
    ("客厅",       "living",          "mdi:sofa"),
    ("大厅",       "living",          "mdi:sofa"),
    ("餐厅",       "dining",          "mdi:silverware-fork-knife"),
    ("厨房",       "kitchen",         "mdi:fridge-outline"),
    ("书房",       "study",           "mdi:desk"),
    ("办公室",     "office",          "mdi:briefcase-outline"),
    ("浴室",       "bathroom",        "mdi:shower"),
    ("卫生间",     "bathroom",        "mdi:shower"),
    ("洗手间",     "bathroom",        "mdi:shower"),
    ("厕所",       "bathroom",        "mdi:shower"),
    ("盥洗室",     "bathroom",        "mdi:shower"),
    ("阳台",       "balcony",         "mdi:flower-outline"),
    ("露台",       "terrace",         "mdi:flower"),
    ("院子",       "courtyard",       "mdi:tree"),
    ("庭院",       "courtyard",       "mdi:tree"),
    ("花园",       "garden",          "mdi:flower"),
    ("车库",       "garage",          "mdi:garage"),
    ("门厅",       "hallway",         "mdi:door-open"),
    ("玄关",       "entrance",        "mdi:door-open"),
    ("过道",       "hallway",         "mdi:walk"),
    ("走廊",       "hallway",         "mdi:walk"),
    ("储藏室",     "storage",         "mdi:archive"),
    ("储物间",     "storage",         "mdi:archive"),
    ("衣帽间",     "wardrobe",        "mdi:hanger"),
    ("健身房",     "gym",             "mdi:dumbbell"),
    ("琴房",       "music-room",      "mdi:music-note"),
    ("影音室",     "media-room",      "mdi:movie-open-outline"),
    ("地下室",     "basement",        "mdi:home-downstairs-outline"),
    ("楼梯间",     "stairs",          "mdi:stairs"),
    ("鱼缸",       "aquarium",        "mdi:fishbowl"),
    ("宠物房",     "pet-room",        "mdi:dog-side"),
    ("阳台房",     "balcony",         "mdi:flower-outline"),
    ("智能插座",   "sockets",         "mdi:power-plug"),
    ("汽车",       "car",             "mdi:car"),
    ("su7",        "su7",             "mdi:car"),
    ("离线设备",   "offline",         "mdi:cloud-off-outline"),
    ("其他设备",   "others",          "mdi:dots-horizontal"),
]

DEFAULT_AREA_ICON = "mdi:home-outline"
OFFLINE_KEY = "__offline__"


def _stable_hash(text, n=6):
    """稳定短哈希：同样的输入永远得到同样的输出（跨进程、跨机器一致）。"""
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:n]


def guess_area_slug_and_icon(name, area_id=""):
    """按房间名推断 (slug, icon)。推断不出时用 area_id 派生稳定 slug。"""
    n = (name or "").strip()
    for kw, slug, icon in ROOM_TABLE:
        if n == kw:
            return slug, icon
    for kw, slug, icon in ROOM_TABLE:
        if kw and kw in n:
            return slug, icon
    # 推断不出：slug 用 area_id 派生（稳定、可读性一般但绝不冲突/漂移）
    seed = area_id or n or "area"
    return "room-" + _stable_hash(seed), DEFAULT_AREA_ICON


def slugify_device(name):
    """设备 slug：沿用中文可读风格（HA 的 URL path 支持中文）。"""
    s = re.sub(r"[^\w一-鿿]+", "-", name or "").strip("-").lower()
    return s or "device"


class SyncState:
    """持久化的稳定标识映射表。"""

    def __init__(self, path, overrides_path=None):
        self.path = path
        self.data = {
            "version": STATE_VERSION,
            "areas": {},
            "devices": {},
        }
        self.changes = []
        self.overrides = {}
        self._load_overrides(overrides_path)
        self._load()

    # ------------------------------------------------------------------
    def _load_overrides(self, overrides_path=None):
        """加载人工覆盖配置（朋友可自行改图标/改显示名/改 slug）。

        查找顺序：显式参数 > 环境变量 MI_OVERRIDES >
                  state.json 同目录下的 mi-overrides.json
        格式:
          {"areas": {"<area_id>": {"slug": "...", "icon": "mdi:...", "title": "..."}},
           "areas_by_name": {"客厅": {"icon": "mdi:..."}},
           "devices": {"<device_id>": {"title": "显示名"}}}
        """
        if overrides_path is None:
            overrides_path = os.environ.get("MI_OVERRIDES")
        if not overrides_path and self.path:
            cand = os.path.join(os.path.dirname(self.path), "mi-overrides.json")
            if os.path.exists(cand):
                overrides_path = cand
        if not overrides_path or not os.path.exists(overrides_path):
            self.overrides_path = None
            return
        try:
            with open(overrides_path, encoding="utf-8") as f:
                self.overrides = json.load(f) or {}
        except Exception:
            self.overrides = {}
        self.overrides_path = overrides_path

    def _override_for_area(self, area_id, name):
        ov = (self.overrides.get("areas") or {}).get(area_id)
        if not ov:
            ov = (self.overrides.get("areas_by_name") or {}).get(name or "")
        return ov or {}

    # ------------------------------------------------------------------
    def _load(self):
        if not self.path or not os.path.exists(self.path):
            return
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return
        if isinstance(data, dict):
            self.data.setdefault("areas", {})
            self.data.setdefault("devices", {})
            for k in ("areas", "devices"):
                if isinstance(data.get(k), dict):
                    self.data[k].update(data[k])

    def save(self):
        if not self.path:
            return
        d = os.path.dirname(self.path)
        if d:
            os.makedirs(d, exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)

    # ------------------------------------------------------------------
    def _pick_area_slug(self, name, key):
        """slug 优先级：旧版迁移 > area_id 派生 > 名称推断 > 哈希兜底。"""
        legacy = LEGACY_AREA_PATH.get(name or "")
        if legacy:
            return legacy
        byid = slug_from_area_id(key)
        if byid:
            return byid
        guessed, _ = guess_area_slug_and_icon(name, key)
        if guessed and not guessed.startswith("room-"):
            return guessed
        return "room-" + _stable_hash(key or name or "area")

    def _infer_icon_with_src(self, name, key):
        """推断区域图标，并记录来源（决定改名时是否重新推断）。"""
        n = (name or "").strip()
        for kw, _slug, icon in ROOM_TABLE:
            if n == kw:
                return icon, "name"
        for kw, _slug, icon in ROOM_TABLE:
            if kw and kw in n:
                return icon, "name"
        legacy = LEGACY_AREA_ICON.get(name or "")
        if legacy:
            return legacy, "legacy"
        return DEFAULT_AREA_ICON, "default"

    def area(self, area_id, name):
        """取（并按需初始化）一个区域的 slug / icon / title。"""
        key = area_id or OFFLINE_KEY
        ov = self._override_for_area(key, name)
        rec = self.data["areas"].get(key)
        if rec:
            old_title = rec.get("title")
            new_title = ov.get("title") or name
            if old_title != new_title:
                rec["title"] = new_title
                self.changes.append({
                    "type": "area_renamed", "id": key,
                    "from": old_title, "to": new_title,
                    "slug": rec.get("slug"), "icon": rec.get("icon"),
                })
            # 图标来源是「自动推断」时，改名后重新推断；用户指定的永不动
            if rec.get("icon_src") in ("name", "default"):
                new_icon, new_src = self._infer_icon_with_src(new_title, key)
                if new_icon != rec.get("icon"):
                    rec["icon"] = new_icon
                    rec["icon_src"] = new_src
            if ov.get("icon"):
                rec["icon"] = ov["icon"]
                rec["icon_src"] = "override"
            if ov.get("slug"):
                rec["slug"] = ov["slug"]
            return rec

        slug = ov.get("slug") or self._pick_area_slug(name, key)
        icon, src = self._infer_icon_with_src(name, key)
        if ov.get("icon"):
            icon, src = ov["icon"], "override"
        slug = self._unique_area_slug(slug, key)
        rec = {"slug": slug, "icon": icon, "icon_src": src, "title": name}
        self.data["areas"][key] = rec
        self.changes.append({
            "type": "area_added", "id": key, "title": name,
            "slug": slug, "icon": icon,
        })
        return rec

    def _unique_area_slug(self, base, key):
        """同一个 slug 被不同 area 占用时加后缀（保持稳定：按 key 派生）。"""
        used = {r.get("slug"): k for k, r in self.data["areas"].items()}
        if base not in used or used[base] == key:
            return base
        alt = "%s-%s" % (base, _stable_hash(key, 4))
        i = 2
        while alt in used and used[alt] != key:
            alt = "%s-%s-%d" % (base, _stable_hash(key, 4), i)
            i += 1
        return alt

    # ------------------------------------------------------------------
    def device(self, device_id, name):
        """取（并按需初始化）一个设备的 slug / title（title 即显示名）。"""
        key = device_id or ""
        ov = (self.overrides.get("devices") or {}).get(key) or {}
        rec = self.data["devices"].get(key)
        if rec:
            old_title = rec.get("title")
            new_title = ov.get("title") or name
            if old_title != new_title:
                rec["title"] = new_title
                self.changes.append({
                    "type": "device_renamed", "id": key,
                    "from": old_title, "to": new_title, "slug": rec.get("slug"),
                })
            if ov.get("slug"):
                rec["slug"] = ov["slug"]
            return rec
        slug = ov.get("slug") or slugify_device(ov.get("title") or name)
        slug = self._unique_device_slug(slug, key)
        rec = {"slug": slug, "title": ov.get("title") or name}
        self.data["devices"][key] = rec
        self.changes.append({
            "type": "device_added", "id": key,
            "title": ov.get("title") or name, "slug": slug,
        })
        return rec

    def _unique_device_slug(self, base, key):
        used = {r.get("slug"): k for k, r in self.data["devices"].items()}
        if base not in used or used[base] == key:
            return base
        alt = "%s-%s" % (base, _stable_hash(key, 4))
        i = 2
        while alt in used and used[alt] != key:
            alt = "%s-%s-%d" % (base, _stable_hash(key, 4), i)
            i += 1
        return alt

    # ------------------------------------------------------------------
    def prune(self, live_area_ids, live_device_ids):
        """清理已删除的记录（保留一小段时间内的房间，便于房间重建时复用 slug）。"""
        removed = []
        for key in list(self.data["areas"].keys()):
            if key == OFFLINE_KEY:
                continue
            if key not in live_area_ids:
                removed.append({"type": "area_removed", "id": key,
                                "title": self.data["areas"][key].get("title")})
                # 不立刻删除记录：房间可能被重建，保留 slug 有利于链接延续
        for key in list(self.data["devices"].keys()):
            if key not in live_device_ids:
                removed.append({"type": "device_removed", "id": key,
                                "title": self.data["devices"][key].get("title")})
                self.data["devices"].pop(key, None)
        self.changes.extend(removed)
        return removed

    def report(self):
        """人类可读的变更摘要。"""
        if not self.changes:
            return "无变化（房间/设备与上次同步一致）"
        icons = {
            "area_added": "新增房间", "area_removed": "移除房间",
            "area_renamed": "房间改名", "device_added": "新增设备",
            "device_removed": "移除设备", "device_renamed": "设备改名",
        }
        lines = []
        for c in self.changes:
            label = icons.get(c["type"], c["type"])
            if c["type"].endswith("_renamed"):
                lines.append("  %s: %s -> %s（URL 不变: %s）"
                             % (label, c.get("from"), c.get("to"), c.get("slug")))
            elif c["type"] == "area_added":
                lines.append("  %s: %s（slug=%s, 图标=%s）"
                             % (label, c.get("title"), c.get("slug"), c.get("icon")))
            else:
                lines.append("  %s: %s" % (label, c.get("title")))
        return "\n".join(lines)


if __name__ == "__main__":
    import sys
    st = SyncState(sys.argv[1] if len(sys.argv) > 1 else "/tmp/mi-cards-state.json")
    print("状态文件:", st.path)
    print("区域记录:", len(st.data["areas"]), "| 设备记录:", len(st.data["devices"]))
