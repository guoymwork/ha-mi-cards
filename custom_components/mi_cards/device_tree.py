"""设备树构建：直接从 HA 的实体/设备/区域注册表派生面板结构。

与原先「拉快照 -> 离线生成 YAML」的做法相比，这里在 HA 进程内直接读注册表，
因此房间或设备的增删改名会立刻反映到面板上，无需任何外部同步任务。

输出的设备树与前端卡片期望的结构一一对应：

    {
      "areas": [
        {"id": ..., "name": "客厅", "icon": "mdi:sofa", "slug": "living",
         "devices": [ {device...}, ... ]}
      ],
      "devices": { "<device_id>": {device...} }
    }
"""

from __future__ import annotations

import re
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .const import DEFAULT_ACCENT

# --------------------------------------------------------------------------
# 图标 / 名称
# --------------------------------------------------------------------------

DOMAIN_ICON = {
    "switch": "mdi:power",
    "light": "mdi:lightbulb",
    "climate": "mdi:thermostat",
    "water_heater": "mdi:water-boiler",
    "fan": "mdi:fan",
    "cover": "mdi:window-shutter",
    "vacuum": "mdi:robot-vacuum",
    "humidifier": "mdi:air-humidifier",
    "media_player": "mdi:speaker",
    "number": "mdi:numeric",
    "select": "mdi:format-list-bulleted",
    "sensor": "mdi:eye-outline",
    "binary_sensor": "mdi:check-circle-outline",
    "button": "mdi:gesture-tap-button",
    "input_button": "mdi:gesture-tap-button",
    "text": "mdi:text",
    "event": "mdi:gesture-tap-button",
}

# 明显是内部/无用实体的关键词
SKIP_KEYWORDS = ("工厂测试", "设备自定义功能", "固件", "spec", "Spec")

# 纳入面板的厂商前缀（米家生态为主，另加少数独立集成）
INCLUDE_PREFIX = (
    "xiaomi", "zimi", "cuco", "giot", "miir", "chuangmi", "lumi", "linp",
    "chunmi", "yunmi", "huizuo", "loock", "aqara", "viomi", "nwt", "ddp",
    "scishare", "youpin", "roborock", "yeelight", "rockrobo", "shp",
    "nina", "good", "song", "ipc", "xiaojia", "dks",
)

# 主实体（xiaomi_home 的 _s_ 实体）
MAIN_RE = re.compile(r"_s_\d+_")
PROP_RE = re.compile(r"_p_\d+")
ACT_RE = re.compile(r"_a_\d+")
IR_ON_RE = re.compile(r"_turn_on_a_")
IR_OFF_RE = re.compile(r"_turn_off_a_")

SWITCHABLE_DOMAINS = (
    "media_player", "vacuum", "climate", "water_heater",
    "fan", "cover", "humidifier", "lock", "light", "switch",
)

# 非米家集成（如石头 roborock）的英文实体名 -> 中文
EN_NAME_ZH = {
    "Resolve dock error": "基站断连恢复",
    "Resume dock error": "基站断连恢复",
    "Mop washing": "基站洗拖布",
    "Mop drying": "基站烘干拖布",
    "Dust bag full": "集尘袋已满",
    "Side brush": "边刷",
    "Main brush": "主刷",
    "Filter": "滤网",
    "Dock water filter": "基站水滤芯",
    "Mop intensity": "拖地强度",
    "Mop mode": "拖地模式",
    "Cleaning mode": "清扫模式",
    "Selected map": "当前地图",
    "Water box": "水箱",
    "Clean water tank": "清水箱",
    "Waste water tank": "污水箱",
    "Dust collection": "集尘",
    "Volume": "音量",
    "Cleaning": "正在清扫",
    "Charging": "正在充电",
    "Water shortage": "缺水",
    "Mop attached": "已装拖把",
    "Water box attached": "已装水箱",
    "Main brush remaining time": "主刷剩余时间",
    "Side brush remaining time": "边刷剩余时间",
    "Dust bag remaining time": "集尘袋剩余时间",
    "Filter remaining time": "滤芯剩余时间",
    "Dock clean water tank remaining time": "基站清水箱剩余时间",
    "Clean water tank remaining time": "清水箱剩余时间",
    "Waste water tank remaining time": "污水箱剩余时间",
    "Off peak charging": "闲时充电",
    "Off peak start time": "闲时开始时间",
    "Off peak end time": "闲时结束时间",
    "Map 0": "地图",
    "Fan speed": "风速",
    "Current mode": "当前模式",
    "Current fan speed": "当前风速",
    "Current temperature": "当前温度",
    "Target temperature": "目标温度",
    "Current humidity": "当前湿度",
    "Battery level": "电量",
    "Signal strength": "信号强度",
    "Status": "状态",
    "Mode": "模式",
    "Level": "档位",
    "Power": "电源",
}

# 区域顺序：常见起居空间优先
ROOM_ORDER = (
    "客厅", "起居室", "大厅", "餐厅", "厨房", "主卧", "次卧", "卧室", "书房",
    "卫生间", "浴室", "阳台", "院子", "庭院", "车库", "门厅", "玄关",
)

# 房间名 -> (英文 slug, mdi 图标)
ROOM_TABLE = (
    ("主卧", "master-bedroom", "mdi:bed-king-outline"),
    ("次卧", "second-bedroom", "mdi:bed-outline"),
    ("儿童房", "kids-room", "mdi:baby-face-outline"),
    ("老人房", "elder-room", "mdi:human-male-female-child"),
    ("婴儿房", "nursery", "mdi:baby"),
    ("卧室", "bedroom", "mdi:bed-outline"),
    ("主卧房", "master-bedroom", "mdi:bed-king-outline"),
    ("客房", "guest-room", "mdi:bed-outline"),
    ("起居室", "living", "mdi:sofa"),
    ("客厅", "living", "mdi:sofa"),
    ("大厅", "living", "mdi:sofa"),
    ("餐厅", "dining", "mdi:silverware-fork-knife"),
    ("厨房", "kitchen", "mdi:fridge-outline"),
    ("书房", "study", "mdi:desk"),
    ("办公室", "office", "mdi:briefcase-outline"),
    ("浴室", "bathroom", "mdi:shower"),
    ("卫生间", "bathroom", "mdi:shower"),
    ("洗手间", "bathroom", "mdi:shower"),
    ("厕所", "bathroom", "mdi:shower"),
    ("盥洗室", "bathroom", "mdi:shower"),
    ("阳台", "balcony", "mdi:flower-outline"),
    ("露台", "terrace", "mdi:flower"),
    ("院子", "courtyard", "mdi:tree"),
    ("庭院", "courtyard", "mdi:tree"),
    ("花园", "garden", "mdi:flower"),
    ("车库", "garage", "mdi:garage"),
    ("门厅", "hallway", "mdi:door-open"),
    ("玄关", "entrance", "mdi:door-open"),
    ("过道", "hallway", "mdi:walk"),
    ("走廊", "hallway", "mdi:walk"),
    ("储藏室", "storage", "mdi:archive"),
    ("储物间", "storage", "mdi:archive"),
    ("衣帽间", "wardrobe", "mdi:hanger"),
    ("健身房", "gym", "mdi:dumbbell"),
    ("琴房", "music-room", "mdi:music-note"),
    ("影音室", "media-room", "mdi:movie-open-outline"),
    ("地下室", "basement", "mdi:home-downstairs-outline"),
    ("楼梯间", "stairs", "mdi:stairs"),
    ("鱼缸", "aquarium", "mdi:fishbowl"),
    ("宠物房", "pet-room", "mdi:dog-side"),
    ("阳台房", "balcony", "mdi:flower-outline"),
    ("智能插座", "sockets", "mdi:power-plug"),
    ("汽车", "car", "mdi:car"),
    ("su7", "su7", "mdi:car"),
)


def _slugify(text: str) -> str:
    """把名称转成 URL 友好的 slug（保留中文，HA 的 path 支持中文）。"""
    s = re.sub(r"[^\w一-鿿]+", "-", text or "").strip("-").lower()
    return s or "device"


def guess_area_slug_and_icon(name: str, area_id: str = "") -> tuple[str, str]:
    """按房间名推断 (slug, icon)；推断不出时用 area_id 派生稳定 slug。"""
    n = (name or "").strip()
    for kw, slug, icon in ROOM_TABLE:
        if n == kw:
            return slug, icon
    for kw, slug, icon in ROOM_TABLE:
        if kw and kw in n:
            return slug, icon
    import hashlib

    seed = area_id or n or "area"
    return "room-" + hashlib.sha1(seed.encode("utf-8")).hexdigest()[:6], "mdi:home-outline"


def clean_name(fname: str, devname: str) -> str:
    """去掉设备名前缀，并把常见英文实体名翻译成中文。"""
    s = fname or ""
    if devname and s.startswith(devname):
        s = s[len(devname):]
    s = s.replace("*", " ")
    s = re.sub(r"\s+", " ", s).strip()
    if s in EN_NAME_ZH:
        return EN_NAME_ZH[s]
    for en, zh in EN_NAME_ZH.items():
        if s.startswith(en) and len(s) > len(en):
            tail = s[len(en):].strip(" -_")
            return zh + (" · " + tail if tail else "")
    return s


def _entity_dict(entity_id: str, state: Any, area_id: str | None) -> dict[str, Any]:
    """把一个实体状态转成面板用的精简结构。"""
    attrs = dict(state.attributes) if state is not None else {}
    return {
        "entity_id": entity_id,
        "domain": entity_id.split(".")[0],
        "name": attrs.get("friendly_name", entity_id),
        "state": state.state if state is not None else "unavailable",
        "attrs": attrs,
        "area_id": area_id,
    }


def _pick_main(ents: list[dict[str, Any]]) -> dict[str, Any] | None:
    """挑选设备的主实体（卡片展示与开关操作的对象）。"""
    for e in ents:
        if MAIN_RE.search(e["entity_id"]):
            return e
    for dom in SWITCHABLE_DOMAINS:
        for e in ents:
            eid = e["entity_id"]
            if e["domain"] != dom:
                continue
            if PROP_RE.search(eid) or ACT_RE.search(eid):
                continue
            return e
    for dom in SWITCHABLE_DOMAINS:
        for e in ents:
            if e["domain"] == dom:
                return e
    for e in ents:
        if e["domain"] == "binary_sensor":
            return e

    def _sensor(dc: str | None) -> dict[str, Any] | None:
        for e in ents:
            if e["domain"] != "sensor":
                continue
            a = e["attrs"] or {}
            if a.get("device_class") == "enum":
                continue
            if dc is None or a.get("device_class") == dc:
                return e
        return None

    for want_dc in ("temperature", "battery", "humidity"):
        e = _sensor(want_dc)
        if e:
            return e
    e = _sensor(None)
    if e:
        return e
    for dom in ("number", "select"):
        for e in ents:
            if e["domain"] == dom:
                return e
    for dom in ("event", "button", "input_button"):
        for e in ents:
            if e["domain"] == dom:
                return e
    return ents[0] if ents else None


def _pick_power_switch(
    ents: list[dict[str, Any]], main: dict[str, Any] | None
) -> dict[str, Any] | None:
    """挑选电源开关实体。"""
    if main and main["domain"] == "media_player":
        # 音箱/播放器没有独立电源开关，右上角按钮直接控制播放
        return None
    for e in ents:
        if e["domain"] != "switch":
            continue
        n = e["name"]
        if "开关状态" in n or n.endswith("开关") or "开关" in n.split()[-1]:
            return e
    for e in ents:
        if e["domain"] == "switch" and e is not main:
            return e
    return None


def _pick_status_sensor(
    ents: list[dict[str, Any]], main: dict[str, Any] | None
) -> dict[str, Any] | None:
    """挑选状态枚举传感器。"""
    for e in ents:
        if e["domain"] == "sensor" and (e["attrs"] or {}).get("device_class") == "enum":
            return e
    return None


def build_device_tree(
    hass: HomeAssistant,
    image_map: dict[str, str] | None = None,
    accent: str = DEFAULT_ACCENT,
) -> dict[str, Any]:
    """构建整棵设备树。"""
    ent_reg = er.async_get(hass)
    dev_reg = dr.async_get(hass)
    area_reg = ar.async_get(hass)

    images = image_map or {}

    # 区域 id -> 名称
    areas_by_id: dict[str, str] = {}
    for area in area_reg.areas.values():
        areas_by_id[area.id] = area.name

    # 设备 id -> 该设备的实体列表
    ents_by_device: dict[str, list[dict[str, Any]]] = {}
    for entry in ent_reg.entities.values():
        if entry.disabled_by is not None:
            continue
        state = hass.states.get(entry.entity_id)
        if state is None:
            continue
        if entry.device_id is None:
            continue
        ents_by_device.setdefault(entry.device_id, []).append(
            _entity_dict(entry.entity_id, state, entry.area_id)
        )

    devices: list[dict[str, Any]] = []
    for device in dev_reg.devices:
        model = device.model or ""
        if not model:
            continue
        brand = model.split(".")[0] if "." in model else ""
        ents = ents_by_device.get(device.id, [])
        if not ents:
            continue
        if brand not in INCLUDE_PREFIX and not _has_miot_entity(ents):
            continue

        info = _build_device(device, ents, areas_by_id, images, accent)
        if info:
            devices.append(info)

    devices = _merge_dock_devices(devices)

    # 按区域分组
    groups: dict[str, dict[str, Any]] = {}
    for d in devices:
        aid = d.get("area_id") or ""
        name = d.get("area") or "其他设备"
        g = groups.setdefault(aid, {"name": name, "items": []})
        g["items"].append(d)

    def area_sort_key(aid: str) -> tuple:
        name = groups[aid]["name"]
        if name in ROOM_ORDER:
            return (0, ROOM_ORDER.index(name))
        return (1, -len(groups[aid]["items"]), name)

    area_list = []
    for aid in sorted(groups.keys(), key=area_sort_key):
        name = groups[aid]["name"]
        if name == "其他设备":
            continue
        slug, icon = guess_area_slug_and_icon(name, aid)
        area_list.append(
            {
                "id": aid,
                "name": name,
                "slug": slug,
                "icon": icon,
                "devices": groups[aid]["items"],
            }
        )

    return {
        "areas": area_list,
        "devices": {d["device_id"]: d for d in devices},
        "other": groups.get("", {}).get("items", []),
    }


def _has_miot_entity(ents: list[dict[str, Any]]) -> bool:
    """实体 id 是否符合 xiaomi_home 的命名特征（<brand>_cn_<did>_...）。"""
    return any(re.match(r"^[a-z_]+\.[a-z]+_cn_[0-9a-z]+_", e["entity_id"]) for e in ents)


def _build_device(
    device: Any,
    ents: list[dict[str, Any]],
    areas_by_id: dict[str, str],
    images: dict[str, str],
    accent: str,
) -> dict[str, Any] | None:
    """把一个 HA 设备转成面板设备结构。"""
    name = device.name_by_user or device.name
    model = device.model or ""
    main = _pick_main(ents)
    if not main:
        return None

    vac = next((e for e in ents if e["domain"] == "vacuum"), None)
    ir_on = next(
        (e for e in ents if e["domain"] == "button" and IR_ON_RE.search(e["entity_id"])),
        None,
    )
    ir_off = next(
        (e for e in ents if e["domain"] == "button" and IR_OFF_RE.search(e["entity_id"])),
        None,
    )

    if vac:
        main = vac
        power = None
    elif ir_on and ir_off:
        main = (
            next((e for e in ents if e["domain"] == "select"), None)
            or next((e for e in ents if e["domain"] == "number"), None)
            or next((e for e in ents if e["domain"] == "sensor"), None)
            or ir_on
        )
        power = None
    else:
        power = _pick_power_switch(ents, main)

    card: dict[str, Any] = {
        "entity": main["entity_id"],
        "name": name,
        "accent": accent,
    }
    if vac:
        card["btn_icon"] = "mdi:broom"
        card["on_state_label"] = "清扫中"
    if ir_on and ir_off:
        card["btn_icon"] = "mdi:power"
        card["action_entity"] = ir_on["entity_id"]
        card["action_entity_off"] = ir_off["entity_id"]
        card["state_label"] = "红外遥控"
        card["on_state_label"] = "已开启"

    img = images.get(model)
    if img:
        card["image"] = img
    else:
        card["icon"] = DOMAIN_ICON.get(main["domain"], "mdi:help-circle-outline")

    if power and power["entity_id"] != main["entity_id"]:
        card["switch_entity"] = power["entity_id"]
    if main["domain"] in ("switch", "light", "climate", "water_heater"):
        card["on_state_label"] = "运行中"
        card["off_state_label"] = "已关闭"
    if main["state"] == "unavailable":
        card["state_label"] = "设备离线"
        card["off_state_label"] = "设备离线"

    detail = _build_detail(device, name, main, power, ents, img, accent)

    area_id = device.area_id or main.get("area_id")
    area = areas_by_id.get(area_id or "", "") or "其他设备"
    if area != "其他设备":
        card["group"] = area

    return {
        "device_id": device.id,
        "name": name,
        "model": model,
        "slug": _slugify(name),
        "area": area,
        "area_id": area_id,
        "card": card,
        "detail": detail,
        "main": main["entity_id"],
        "switch_entity": (power or {}).get("entity_id"),
    }


def _build_detail(
    device: Any,
    name: str,
    main: dict[str, Any],
    power: dict[str, Any] | None,
    ents: list[dict[str, Any]],
    img: str | None,
    accent: str,
) -> dict[str, Any]:
    """构建设备详情页配置。"""
    detail: dict[str, Any] = {
        "title": name,
        "accent": accent,
    }
    if img:
        detail["image"] = img

    if "current_temperature" in (main["attrs"] or {}):
        gauge: dict[str, Any] = {
            "entity": main["entity_id"],
            "value_attribute": "current_temperature",
            "unit": main["attrs"].get("temperature_unit", "°C"),
            "label": "当前温度",
        }
        st_sensor = _pick_status_sensor(ents, main)
        if st_sensor:
            gauge["status_entity"] = st_sensor["entity_id"]
            opts = st_sensor["attrs"].get("options") or []
            gauge["status_map"] = {
                o: {
                    "Keep-warming": "保温中",
                    "Heat": "加热中",
                    "Idle": "待机",
                    "Cooling": "制冷中",
                }.get(o, o)
                for o in opts
            }
        detail["gauge"] = gauge

    if power:
        detail["power"] = {
            "entity": power["entity_id"],
            "on_label": "关机",
            "off_label": "开机",
        }

    ops = main["attrs"].get("operation_list") or []
    if len(ops) >= 2:
        labels = {
            "低档": ("L", "低温"), "中档": ("M", "中温"), "高档": ("H", "高温"),
            "低温": ("L", "低温"), "中温": ("M", "中温"), "高温": ("H", "高温"),
        }
        opts = []
        for o in ops:
            if o == "off":
                continue
            lab, sub = labels.get(o, (o, ""))
            opts.append({"value": o, "label": lab, "sub": sub})
        if len(opts) >= 2:
            detail["choices"] = [
                {
                    "entity": main["entity_id"],
                    "title": "目标温度",
                    "options": opts,
                    "service": f"{main['domain']}.set_operation_mode",
                    "value_key": "operation_mode",
                }
            ]

    used = {main["entity_id"], (power or {}).get("entity_id")}
    rows = []
    for e in ents:
        if e["entity_id"] in used:
            continue
        if e["domain"] in ("update", "event", "image", "camera", "calendar"):
            continue
        nm = clean_name(e["name"], name)
        if any(k in nm for k in SKIP_KEYWORDS):
            continue
        if not nm:
            nm = e["entity_id"]
        dc = (e["attrs"] or {}).get("device_class")
        if dc in ("timestamp", "duration"):
            continue
        low_value_kw = (
            "总清扫", "总清洁", "清扫次数", "清洁面积", "进度",
            "当前房间", "所选地图", "地图", "坐标", "上次",
            "清洁区域", "请勿打扰开始", "请勿打扰结束",
        )
        if any(k in nm for k in low_value_kw):
            continue
        row: dict[str, Any] = {
            "entity": e["entity_id"],
            "name": nm,
            "icon": DOMAIN_ICON.get(e["domain"], "mdi:help-circle-outline"),
        }
        if e["domain"] == "number" and (e["attrs"] or {}).get("max", 100) <= 3:
            row["as_switch"] = True
        rows.append(row)
    if rows:
        detail["entities"] = rows[:14]

    _refine_water_heater(device, main, ents, detail, img, accent)
    return detail


def _refine_water_heater(
    device: Any,
    main: dict[str, Any],
    ents: list[dict[str, Any]],
    detail: dict[str, Any],
    img: str | None,
    accent: str,
) -> None:
    """小厨宝精修：全部按「关键词 + 域」动态发现，不写死实体 id。"""
    if (device.model or "") != "zimi.waterheater.h03":
        return
    if not ents:
        return

    def find(kw: str, domain: str | None = None) -> dict[str, Any] | None:
        for e in ents:
            eid = e["entity_id"]
            if domain and e["domain"] != domain:
                continue
            if kw in eid:
                return e
        return None

    heater = find("_s_", "water_heater") or find("", "water_heater")
    power_sw = find("_on_p_", "switch") or find("_switch_on", "switch")
    status = find("status", "sensor") or find("_status", "sensor")

    rows = []
    for e, nm, ic in (
        (find("sterilization"), "一键杀菌", "mdi:spray-bottle"),
        (find("freeze", "switch"), "防冻提醒", "mdi:snowflake"),
        (find("timer", "text") or find("timer", "switch"), "定时开关机", "mdi:clock-outline"),
        (find("cloud_timer", "switch"), "云端定时", "mdi:timer-outline"),
        (find("fault", "sensor"), "故障状态", "mdi:alert-circle-outline"),
    ):
        if e:
            rows.append({"entity": e["entity_id"], "name": nm, "icon": ic})

    detail["subtitle"] = "浴室 · 7L 即热"
    if img:
        detail["image"] = img
    if heater:
        gauge = {
            "entity": heater["entity_id"],
            "value_attribute": "current_temperature",
            "unit": heater["attrs"].get("temperature_unit", "°C"),
            "label": "当前温度",
        }
        if status:
            gauge["status_entity"] = status["entity_id"]
            gauge["status_map"] = {
                "Keep-warming": "保温中", "Heat": "加热中",
                "Idle": "待机", "Cooling": "制冷中",
            }
        detail["gauge"] = gauge
    if power_sw:
        detail["power"] = {
            "entity": power_sw["entity_id"],
            "on_label": "关机",
            "off_label": "开机",
        }
    if heater:
        detail["choices"] = [
            {
                "entity": heater["entity_id"],
                "title": "目标温度",
                "options": [
                    {"value": "低档", "label": "L", "sub": "低温"},
                    {"value": "中档", "label": "M", "sub": "中温"},
                    {"value": "高档", "label": "H", "sub": "高温"},
                ],
                "service": "water_heater.set_operation_mode",
                "value_key": "operation_mode",
                "current_attribute": "operation_mode",
            }
        ]
    if rows:
        detail["entities"] = rows


def _merge_dock_devices(devices: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """把基座（model 以 " Dock" 结尾）合并到主机那张卡上。

    例：石头「P20 Pro」与「P20 Pro Dock」在 HA 里是两个 device，
    但对用户而言是一台扫地机。匹配用「型号去 Dock 后缀」而非设备名 ——
    设备改名后仍然能正确合并。
    """
    by_name: dict[str, dict[str, Any]] = {}
    by_model: dict[str, dict[str, Any]] = {}
    for d in devices:
        by_name.setdefault(d["name"], d)
        m = d.get("model") or ""
        if m.endswith(" Dock"):
            by_model.setdefault(m[:-5].strip(), d)

    merged = []
    for d in devices:
        model = d.get("model") or ""
        if model.endswith(" Dock"):
            host = by_name.get(d["name"][:-5].strip()) or by_model.get(model[:-5].strip())
            if host:
                ents = d["detail"].get("entities") or []
                if ents:
                    have = {e["entity"] for e in host["detail"].get("entities") or []}
                    add = [e for e in ents if e["entity"] not in have]
                    if add:
                        host["detail"]["entities"] = (
                            host["detail"].get("entities") or []
                        ) + add
                continue  # 不单独出卡片
        merged.append(d)
    return merged
