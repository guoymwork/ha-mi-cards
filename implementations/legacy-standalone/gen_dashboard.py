#!/usr/bin/env python3
"""生成「设备」面板（米家风格设备卡片）的 Lovelace 配置。

输入:
  /tmp/ha_states.json      HA 全部实体状态
  /tmp/ha_registries.json  实体/设备/区域注册表
  /tmp/mi-images.json      型号 -> 实物图 URL（小米智能家居百科）
输出:
  /tmp/device_dashboard.json
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sync_state import SyncState, OFFLINE_KEY  # noqa: E402

WORK = os.environ.get("MI_WORK_DIR") or "/tmp"
STATES_FILE = os.path.join(WORK, "ha_states.json")
REG_FILE = os.path.join(WORK, "ha_registries.json")
OUT_FILE = os.path.join(WORK, "device_dashboard.json")
PHOTOS_FILE = os.path.join(WORK, "mi-images.json")

STATES = {e["entity_id"]: e for e in json.load(open(STATES_FILE))}
REG = json.load(open(REG_FILE))
ENTS = REG["entity_registry"]["entities"]
DEVS = {d["id"]: d for d in REG["device_registry"]["devices"]}
AREAS = {a.get("area_id") or a["id"]: a["name"] for a in REG["area_registry"]["areas"]}
PHOTOS = {}
if os.path.exists(PHOTOS_FILE):
    PHOTOS = json.load(open(PHOTOS_FILE))

DASH = "device-cards"

# 稳定标识状态文件：记录「区域/设备 ID -> URL slug + 图标」的映射，
# 保证房间改名、设备改名后 URL 不失效。持久化在 NAS 上。
STATE_FILE = os.environ.get("MI_STATE_FILE") or os.path.join(WORK, "mi-cards-state.json")
# 人工覆盖配置（区域图标改名、显示名改写等），可缺省
OVERRIDES_FILE = os.environ.get("MI_OVERRIDES") or None
# 缺图型号清单输出（供自动补图流程消费）
MISSING_FILE = os.environ.get("MI_MISSING_FILE") or os.path.join(WORK, "mi-missing-models.json")

# 图片版本号：图片重新标准化（裁主体/居中）后递增，浏览器缓存自动失效
IMG_VER = os.environ.get("MI_IMG_VER") or "20261112-1"

# 主实体（xiaomi_home 主服务实体 id 中含 _s_）
MAIN_RE = re.compile(r"_s_\d+_")
# 属性（_p_）与动作（_a_）实体不是设备主实体
PROP_RE = re.compile(r"_p_\d+")
ACT_RE = re.compile(r"_a_\d+")
# 红外万能遥控的开关机按钮
IR_ON_RE = re.compile(r"_turn_on_a_")
IR_OFF_RE = re.compile(r"_turn_off_a_")

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
SKIP_KEYWORDS = ["工厂测试", "设备自定义功能", "固件", "spec", "Spec"]


def slugify(name):
    s = re.sub(r"[^\w\u4e00-\u9fff]+", "-", name).strip("-").lower()
    return s or "device"


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


def clean_name(fname, devname):
    s = fname or ""
    if devname and s.startswith(devname):
        s = s[len(devname):]
    s = s.replace("*", " ")
    s = re.sub(r"\s+", " ", s).strip()
    # 英文实体名 -> 中文（去掉设备前缀后仍匹配得上）
    if s in EN_NAME_ZH:
        return EN_NAME_ZH[s]
    for en, zh in EN_NAME_ZH.items():
        if s.startswith(en) and len(s) > len(en):
            tail = s[len(en):].strip(" -_")
            return zh + (" · " + tail if tail else "")
    return s


def device_entities(dev_id):
    out = []
    for e in ENTS:
        if e.get("device_id") == dev_id:
            eid = e["entity_id"]
            st = STATES.get(eid)
            if not st:
                continue
            out.append({
                "entity_id": eid,
                "domain": eid.split(".")[0],
                "name": st["attributes"].get("friendly_name", eid),
                "state": st["state"],
                "attrs": st["attributes"],
                "area_id": e.get("area_id"),
            })
    return out


# ---- 离线设备兜底：注册表里已被移除、但 states 中仍有实体的设备 ----

# xiaomi_home 实体 id 形如 <domain>.<brand>_<cn>_<did>_<model>_<siid>_<prop>...
# 结构: <domain>.<brand>_cn_<did>_<model>_<siid>_<prop>...
# model 本身含点（如 zimi.mosq.v2 -> 品牌段 zimi + 模型 mosq.v2），
# 故从 did 之后按「已知品牌/厂商前缀」切分，而不是贪婪匹配点号。
MIOT_RE = re.compile(
    r"^(?P<dom>[a-z_]+)\."
    r"(?P<brand>[a-z]+)_cn_(?P<did>[0-9a-z]+)_"
    r"(?P<rest>[a-z0-9_.]+)"
)

# 已知的小米生态厂商前缀（用于切分 model）
BRANDS = (
    "zimi", "xiaomi", "cuco", "giot", "miir", "chuangmi", "lumi", "linp",
    "yunmi", "huizuo", "loock", "aqara", "yeelight", "rockrobo", "viomi",
    "chunmi", "nwt", "ddp", "scishare", "shp", "wooo", "youpin", "hdx",
    "nina", "good", "song", "ipc", "vt", "xiaojia", "dks", "lumi", "jy",
)


# 所有已知 model（在线设备注册表提供），用于从实体 id 反查 model
KNOWN_MODELS = set()
for _d in DEVS.values():
    _m = _d.get("model")
    if _m:
        KNOWN_MODELS.add(_m)

# did -> model 映射（xiaomi_home 的实体 id 里型号被精简，无法从 id 反推）
# did 是小米云侧的稳定设备标识
DID_MODEL = {
    "1044030574": "zimi.mosq.v2",
}

# 离线设备的友好名称
DID_NAME = {
    "1044030574": "米家智能驱蚊器2",
}


def split_model(rest, brand, did):
    """由 did 查出 model。

    优先用显式 DID_MODEL 表；其次用已知 model 库按前缀匹配。
    """
    if did in DID_MODEL:
        return DID_MODEL[did].split(".", 1)[1]
    cands = [
        m for m in KNOWN_MODELS
        if m.startswith(brand + ".") and rest.startswith(m.split(".", 1)[1])
    ]
    if cands:
        return max(cands, key=len).split(".", 1)[1]
    return None


def _device_prefix(model, did):
    """由 model + did 推出设备 key，用于聚合同一设备的实体。"""
    return f"{model}|{did}"


def offline_devices():
    """扫描 states，找出注册表中已消失但实体仍在的 xiaomi 设备。

    背景：xiaomi_home 在设备离线且 HA 重启后会把设备从注册表移除，
    但实体仍留在 states 里（unavailable）。这里把它们重新聚合出来，
    保证面板不丢设备（显示离线态）。
    """
    known = {d["id"] for d in DEVS.values()}
    known_entity = {e["entity_id"] for e in ENTS}
    groups = {}
    for eid, st in STATES.items():
        if eid in known_entity:
            continue
        m = MIOT_RE.match(eid)
        if not m:
            continue
        brand = m.group("brand")
        did = m.group("did")
        if brand not in BRANDS:
            continue
        model = split_model(m.group("rest"), brand, did)
        if not model:
            continue
        model = f"{brand}.{model}"
        key = _device_prefix(model, did)
        groups.setdefault(key, {"model": model, "did": did, "entities": []})
        groups[key]["entities"].append({
            "entity_id": eid,
            "domain": eid.split(".")[0],
            "name": st["attributes"].get("friendly_name", eid),
            "state": st["state"],
            "attrs": st["attributes"],
            "area_id": None,
        })
    return groups


OFFLINE = offline_devices()


# 可开关的主实体域（按优先级）
SWITCHABLE_DOMAINS = ("media_player", "vacuum", "climate", "water_heater",
                      "fan", "cover", "humidifier", "lock", "light", "switch")


def pick_main(ents):
    # 1) 主服务实体（xiaomi_home 的 _s_ 实体）
    for e in ents:
        if MAIN_RE.search(e["entity_id"]):
            return e
    # 2) 无属性/动作后缀的主实体（如 media_player.x、vacuum.x）
    for dom in SWITCHABLE_DOMAINS:
        for e in ents:
            eid = e["entity_id"]
            if e["domain"] != dom:
                continue
            if PROP_RE.search(eid) or ACT_RE.search(eid):
                continue
            return e
    # 3) 可开关的设备（保留右上角开关按钮）
    for dom in SWITCHABLE_DOMAINS:
        for e in ents:
            if e["domain"] == dom:
                return e
    # 4) 二值传感器（如驱蚊器的开/关、人体存在）
    for e in ents:
        if e["domain"] == "binary_sensor":
            return e
    # 5) 传感器：温度 > 电量 > 其它（比事件时间戳有意义得多）
    #    跳过枚举型传感器：状态是英文单词（如 Fully），可读性差
    def _sensor(dc):
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
    # 6) 兜底：事件 / 动作按钮
    for dom in ("event", "button", "input_button"):
        for e in ents:
            if e["domain"] == dom:
                return e
    return ents[0] if ents else None


def pick_power_switch(ents, main):
    """找电源开关实体"""
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


def pick_status_sensor(ents, main):
    """状态枚举传感器（如 Keep-warming / Heat）"""
    for e in ents:
        if e["domain"] == "sensor" and e["attrs"].get("device_class") == "enum":
            return e
    return None


IMG_FILES = {}
# 图片目录（成品库）。可用 MI_IMG_DIRS 覆盖，逗号分隔；
# 默认扫描本地工作目录与常见部署目录，避免图片已上线但生成器找不到。
_img_dirs = os.environ.get("MI_IMG_DIRS")
if _img_dirs:
    IMG_DIRS = [d.strip() for d in _img_dirs.split(",") if d.strip()]
else:
    IMG_DIRS = ["/tmp/mi-images", "/tmp/mi-img-work",
                "/vol1/1000/docker/haos/www/mi-images"]
for _d in IMG_DIRS:
    if not os.path.isdir(_d):
        continue
    for fn in os.listdir(_d):
        if fn.startswith("."):
            continue
        # 键保留完整文件名（含扩展名），这样 .png / .webp / .jpg 可以各自命中
        IMG_FILES.setdefault(fn, fn)
        # 另存一份去扩展名的键，用于「型号 -> 任意同名文件」的兜底
        IMG_FILES.setdefault(fn.rsplit(".", 1)[0], fn)

# 型号 -> 官方产品图文件名（miot-spec 的 iotweb-product-center/<pid>.png）
MODEL_IMG = {
    "zimi.waterheater.h03": "zimi_waterheater_h03.webp",
    "zimi.mosq.v1": "zimi_mosq_v1.png",
    "zimi.mosq.v2": "zimi_mosq_v2.png",
    "cuco.plug.v3": "cuco_plug_v3.png",
    "giot.plug.v9icm": "giot_plug_v9icm.png",
    "giot.remote.v51kwm": "giot_remote_v51kwm.png",
    "miir.aircondition.ir02": "miir_aircondition_ir02.png",
    "miir.stb.ir01": "miir_stb_ir01.png",
    "chunmi.cooker.normal2": "chunmi_cooker_normal2.png",
}

# HA 注册型号 -> 米家百科收录型号（部分设备的 HA 型号百科未收录，借用同品牌收录型号的官方图）
BAIKE_ALIAS = {
    # 石头 P20 Pro：HA 型号 roborock.vacuum.a134，百科未收录；
    # 用百科收录的「石头扫地机器人 P5」官方实物图
    "roborock.vacuum.a134": "roborock.vacuum.p5",
    "roborock.vacuum.a134 Dock": "roborock.vacuum.p5",
}


def local_image(model):
    """按型号取本地实物图。

    优先用米家产品百科抓下来的高清图（<model下划线>.png，480x480），
    其次回退到 MODEL_IMG 里手工指定的旧图。

    URL 末尾带 ?v=<版本>：图片重新标准化后浏览器不会继续用缓存的旧图。
    """
    if not model:
        return None
    key = model.replace(".", "_").replace(" ", "_")
    # 尝试的键：完整 -> 去掉 "Dock" 等附属后缀
    keys = [key]
    for suffix in ("_Dock", "_dock"):
        if key.endswith(suffix):
            keys.append(key[: -len(suffix)])

    def url(fn):
        return "/local/mi-images/%s?v=%s" % (fn, IMG_VER)

    # 1) 百科图（fetch_baike_image.py 抓取，命名 = model 里的 . 换成 _）
    for k in keys:
        for ext in (".png", ".jpg", ".jpeg", ".webp"):
            fn = IMG_FILES.get(k + ext)
            if fn:
                return url(fn)
    # 1b) 百科别名：HA 型号百科未收录时，借用百科收录型号的官方图
    alias = BAIKE_ALIAS.get(model)
    if alias:
        ak = alias.replace(".", "_").replace(" ", "_")
        for ext in (".png", ".jpg", ".jpeg", ".webp"):
            fn = IMG_FILES.get(ak + ext)
            if fn:
                return url(fn)
    # 2) 手工指定的旧图
    fn = MODEL_IMG.get(model)
    if fn and fn in IMG_FILES.values():
        return url(fn)
    # 3) 任意同名文件
    for k in keys:
        fn = IMG_FILES.get(k)
        if fn:
            return url(fn)
    return None


def build_device(dev, offline_ents=None):
    dev_id = dev["id"]
    name = dev.get("name_by_user") or dev.get("name")
    model = dev.get("model") or ""
    ents = offline_ents if offline_ents is not None else device_entities(dev_id)
    if not ents:
        return None
    main = pick_main(ents)
    if not main:
        return None
    # 扫地机：卡片主实体改用 vacuum 域实体
    #   （右上角按钮 = 小扫把图标，点击开始/暂停清扫；
    #     勿扰、提示音这类辅助开关留给详情页，不占用卡片按钮）
    vac = next((e for e in ents if e["domain"] == "vacuum"), None)
    # 红外设备（米家万能遥控）：没有状态实体，只有 turn_on / turn_off 按钮，
    #   用它们组成卡片右上角的电源按钮
    ir_on = next((e for e in ents if e["domain"] == "button" and IR_ON_RE.search(e["entity_id"])), None)
    ir_off = next((e for e in ents if e["domain"] == "button" and IR_OFF_RE.search(e["entity_id"])), None)
    if vac:
        main = vac
        power = None
    elif ir_on and ir_off:
        main = next((e for e in ents if e["domain"] == "select"), None) or \
               next((e for e in ents if e["domain"] == "number"), None) or \
               next((e for e in ents if e["domain"] == "sensor"), None) or ir_on
        power = None
    else:
        power = pick_power_switch(ents, main)
    slug = slugify(name)

    card = {
        "type": "custom:mi-device-card",
        "entity": main["entity_id"],
        "name": name,
        "detail_path": f"/{DASH}/{slug}",
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
    img = local_image(model)
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

    # ---- 详情页 ----
    detail = {
        "type": "custom:mi-device-detail",
        "title": name,
        "back_path": f"/{DASH}",
    }
    if img:
        detail["image"] = img

    # 温度圈
    if "current_temperature" in (main["attrs"] or {}):
        g = {
            "entity": main["entity_id"],
            "value_attribute": "current_temperature",
            "unit": main["attrs"].get("temperature_unit", "°C"),
            "label": "当前温度",
        }
        st_sensor = pick_status_sensor(ents, main)
        if st_sensor:
            g["status_entity"] = st_sensor["entity_id"]
            opts = st_sensor["attrs"].get("options") or []
            mapping = {}
            for o in opts:
                mapping[o] = {
                    "Keep-warming": "保温中",
                    "Heat": "加热中",
                    "Idle": "待机",
                    "Cooling": "制冷中",
                }.get(o, o)
            g["status_map"] = mapping
        detail["gauge"] = g

    # 电源
    if power:
        detail["power"] = {
            "entity": power["entity_id"],
            "on_label": "关机",
            "off_label": "开机",
        }

    # 档位选择
    ops = main["attrs"].get("operation_list") or []
    if len(ops) >= 2:
        labels = {"低档": ("L", "低温"), "中档": ("M", "中温"), "高档": ("H", "高温"),
                  "低温": ("L", "低温"), "中温": ("M", "中温"), "高温": ("H", "高温")}
        opts = []
        for o in ops:
            if o == "off":
                continue
            lab, sub = labels.get(o, (o, ""))
            opts.append({"value": o, "label": lab, "sub": sub})
        if len(opts) >= 2:
            detail["choices"] = [{
                "entity": main["entity_id"],
                "title": "目标温度",
                "options": opts,
                "service": f"{main['domain']}.set_operation_mode",
                "value_key": "operation_mode",
            }]

    # 其它常用功能
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
        # 过滤低价值实体：时间戳、时长统计、总量统计、地图/坐标
        dc = e["attrs"].get("device_class")
        if dc in ("timestamp", "duration"):
            continue
        low_value_kw = ("总清扫", "总清洁", "清扫次数", "清洁面积", "进度",
                        "当前房间", "所选地图", "地图", "坐标", "上次",
                        "清洁区域", "请勿打扰开始", "请勿打扰结束")
        if any(k in nm for k in low_value_kw):
            continue
        row = {
            "entity": e["entity_id"],
            "name": nm,
            "icon": DOMAIN_ICON.get(e["domain"], "mdi:help-circle-outline"),
        }
        if e["domain"] == "number" and e["attrs"].get("max", 100) <= 3:
            row["as_switch"] = True
        rows.append(row)
    if rows:
        detail["entities"] = rows[:14]

    dev_area_id = dev.get("area_id")
    return {
        "device_id": dev_id,
        "name": name,
        "model": model,
        "slug": slug,
        "area": AREAS.get(dev_area_id or "") or AREAS.get(main["area_id"] or "") or "",
        "area_id": dev_area_id or main["area_id"],
        "card": card,
        "detail": detail,
        "main": main["entity_id"],
        "switch_entity": (power or {}).get("entity_id"),
    }


def apply_group(dev_info):
    """把区域名写到卡片的 group 字段（用于卡片底部的小字标签）。"""
    area = dev_info.get("area") or ""
    if area and area != "其他设备":
        dev_info["card"]["group"] = area
    return dev_info


def merge_dock_devices(devices):
    """把基座（model 以 " Dock" 结尾）合并到主机那张卡上。

    例：石头「P20 Pro」与「P20 Pro Dock」在 HA 里是两个 device，
    但对用户而言是一台扫地机。合并后只保留主机卡片，
    基座的实体并入主机的详情页功能列表。

    匹配用「型号去 Dock 后缀」而非设备名 —— 设备改名后仍然能正确合并。
    """
    by_name = {}
    by_model = {}
    for d in devices:
        by_name.setdefault(d["name"], d)
        m = (d.get("model") or "")
        if m.endswith(" Dock"):
            by_model.setdefault(m[:-5].strip(), d)
    merged = []
    for d in devices:
        model = d.get("model") or ""
        if model.endswith(" Dock"):
            host = by_name.get(d["name"][:-5].strip()) or by_model.get(model[:-5].strip())
            if host:
                # 基座实体并入主机详情页
                ents = d["detail"].get("entities") or []
                if ents:
                    have = {e["entity"] for e in host["detail"].get("entities") or []}
                    add = [e for e in ents if e["entity"] not in have]
                    if add:
                        host["detail"]["entities"] = (host["detail"].get("entities") or []) + add
                continue  # 不单独出卡片
        merged.append(d)
    return merged


def main():
    # 纳入面板的厂商前缀：米家生态为主，另加少数独立集成（石头等）
    INCLUDE_PREFIX = ("xiaomi", "zimi", "cuco", "giot", "miir", "chuangmi",
                      "lumi", "linp", "chunmi", "yunmi", "huizuo", "loock",
                      "aqara", "viomi", "nwt", "ddp", "scishare", "youpin",
                      "roborock", "yeelight", "rockrobo", "huizuo", "shp",
                      "nina", "good", "song", "ipc", "xiaojia", "dks")

    def is_target_device(dev):
        """判断设备是否该进面板。

        1) 品牌前缀命中米家生态白名单
        2) 实体 id 符合 xiaomi_home 的命名特征（<brand>_cn_<did>_...）
        3) 石头等独立集成靠白名单前缀放行

        注：不依赖任何「集成 config_entry_id」—— 那串 ID 每家每套都不同，
        写死会导致别人的设备一台都进不来。
        """
        model = dev.get("model") or ""
        brand = model.split(".")[0] if "." in model else ""
        if brand and brand in INCLUDE_PREFIX:
            return True
        for e in device_entities(dev["id"]):
            if MIOT_RE.match(e["entity_id"]):
                return True
        return False

    devices = []
    for dev in DEVS.values():
        model = dev.get("model") or ""
        if not model:
            continue
        if not is_target_device(dev):
            continue
        info = build_device(dev)
        if info:
            info["area"] = AREAS.get(dev.get("area_id") or "", "其他设备")
            info["area_id"] = dev.get("area_id")
            apply_group(info)
            devices.append(info)
    devices = merge_dock_devices(devices)

    # 补回离线但实体仍在的设备（注册表已被 xiaomi_home 移除）
    for key, grp in OFFLINE.items():
        did = grp["did"]
        dev = {"id": "offline_" + key.replace("|", "_"),
               "name": DID_NAME.get(did, grp["model"]), "model": grp["model"]}
        info = build_device(dev, offline_ents=grp["entities"])
        if info:
            info["area"] = "离线设备"
            info["area_id"] = OFFLINE_KEY
            info["offline"] = True
            apply_group(info)
            devices.append(info)

    # 小厨宝精修（与米家 App 对齐）
    # 所有实体都靠「关键词 + 域」动态发现，不写死 did ——
    # 写死的话换一台设备（did 不同）详情页就会指向不存在的实体。
    for d in devices:
        if d["model"] != "zimi.waterheater.h03":
            continue
        ents = device_entities(d["device_id"]) or []
        if not ents:
            continue

        def find(kw, domain=None, exclude=()):
            """按实体 id 关键词 + 域找第一个匹配的实体。"""
            for e in ents:
                eid = e["entity_id"]
                if domain and e["domain"] != domain:
                    continue
                if any(x in eid for x in exclude):
                    continue
                if kw in eid:
                    return e
            return None

        heater = find("_s_", "water_heater") or find("", "water_heater")
        power_sw = find("_on_p_", "switch") or find("_switch_on", "switch")
        status = find("status", "sensor") or find("_status", "sensor")
        sterilize = find("sterilization")
        freeze = find("freeze", "switch")
        timer = find("timer", "text") or find("timer", "switch")
        fault = find("fault", "sensor")

        rows = []
        for e, nm, ic in (
            (sterilize, "一键杀菌", "mdi:spray-bottle"),
            (freeze, "防冻提醒", "mdi:snowflake"),
            (timer, "定时开关机", "mdi:clock-outline"),
            (find("cloud_timer", "switch"), "云端定时", "mdi:timer-outline"),
            (fault, "故障状态", "mdi:alert-circle-outline"),
        ):
            if e:
                rows.append({"entity": e["entity_id"], "name": nm, "icon": ic})
                if e["domain"] == "number":
                    rows[-1]["as_switch"] = True

        detail = {
            "type": "custom:mi-device-detail",
            "title": d["name"],
            "subtitle": "浴室 · 7L 即热",
            "back_path": f"/{DASH}",
        }
        img = local_image(d["model"])
        if img:
            detail["image"] = img
        if heater:
            g = {
                "entity": heater["entity_id"],
                "value_attribute": "current_temperature",
                "unit": heater["attrs"].get("temperature_unit", "°C"),
                "label": "当前温度",
            }
            if status:
                g["status_entity"] = status["entity_id"]
                g["status_map"] = {"Keep-warming": "保温中", "Heat": "加热中",
                                   "Idle": "待机", "Cooling": "制冷中"}
            detail["gauge"] = g
        if power_sw:
            detail["power"] = {
                "entity": power_sw["entity_id"],
                "on_label": "关机",
                "off_label": "开机",
            }
        if heater:
            detail["choices"] = [{
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
            }]
        if rows:
            detail["entities"] = rows
        d["detail"] = detail
        d["card"]["on_state_label"] = "保温中"
        d["card"]["off_state_label"] = "已关机"
        if power_sw:
            d["card"]["switch_entity"] = power_sw["entity_id"]

    # ---- 稳定标识：房间/设备的 URL 与图标不再依赖「中文名」----
    # 房间改名、设备改名 -> slug 保持不变（收藏链接继续有效）
    state = SyncState(STATE_FILE, OVERRIDES_FILE)

    # 按区域分组（key = area_id，稳定标识）
    groups = {}
    for d in devices:
        aid = d.get("area_id") or ""
        name = d.get("area") or "其他设备"
        g = groups.setdefault(aid, {"name": name, "items": []})
        g["items"].append(d)

    # 区域顺序：常见起居空间优先，其余按设备数从多到少
    ROOM_ORDER = ["客厅", "餐厅", "厨房", "主卧", "次卧", "卧室", "书房",
                  "卫生间", "浴室", "阳台", "院子", "庭院", "车库", "门厅", "玄关"]
    def area_sort_key(aid):
        name = groups[aid]["name"]
        if name in ROOM_ORDER:
            return (0, ROOM_ORDER.index(name))
        return (1, -len(groups[aid]["items"]), name)

    ordered = []
    for aid in sorted(groups.keys(), key=area_sort_key):
        ordered.extend(groups[aid]["items"])

    # ---- 二级菜单：区域分类直接做成 HA 原生视图（顶部 tab 栏）----
    # 全屋 = 所有设备，卡片底部显示「区域 | 状态」
    # 各区域视图 = 只放该区域设备，卡片底部只显示「状态」（不重复区域名）
    def card_copy(c, show_area):
        d = dict(c)
        d["show_area"] = show_area
        return d

    def wall_of(cards, show_area):
        return {
            "type": "custom:mi-area-wall",
            "cards": [card_copy(c, show_area) for c in cards],
        }

    # 「其他设备」不单独出一个视图，只并入全屋
    area_ids = [a for a in sorted(groups.keys(), key=area_sort_key)
                if groups[a]["name"] != "其他设备"]

    # 每个区域的 slug / 图标由状态层给出（改名不漂移）
    area_meta = {}
    for aid in area_ids:
        name = groups[aid]["name"]
        rec = state.area(aid, name)
        area_meta[aid] = {"name": name, "slug": rec["slug"], "icon": rec["icon"]}

    views = [{
        "type": "sections",
        "title": "全屋",
        "path": "",
        "icon": "mdi:home-outline",
        "show_icon_and_title": True,
        # max_columns=4 + column_span=4 -> section 铺满内容区整宽
        "max_columns": 4,
        "sections": [{
            "type": "grid",
            "column_span": 4,
            "cards": [wall_of([i["card"] for i in ordered], True)],
        }],
    }]

    for aid in area_ids:
        meta = area_meta[aid]
        views.append({
            "type": "sections",
            "title": meta["name"],
            "path": meta["slug"],
            "icon": meta["icon"],
            "show_icon_and_title": True,
            "max_columns": 4,
            "sections": [{
                "type": "grid",
                "column_span": 4,
                "cards": [wall_of([i["card"] for i in groups[aid]["items"]], False)],
            }],
        })

    for d in devices:
        # 设备的 slug 绑定 device_id：设备改名后详情页 URL 不变
        rec = state.device(d["device_id"], d["name"])
        d["slug"] = rec["slug"]
        d["card"]["name"] = rec["title"]
        d["card"]["detail_path"] = f"/{DASH}/{rec['slug']}"
        # 返回路径指向所属区域视图（没有区域则回全屋）
        aid = d.get("area_id") or ""
        back = area_meta.get(aid, {}).get("slug")
        d["detail"]["back_path"] = f"/{DASH}/{back}" if back else f"/{DASH}"
        views.append({
            "type": "sections",
            "title": rec["title"],
            "path": rec["slug"],
            "subview": True,
            "max_columns": 4,
            "sections": [{
                "type": "grid",
                "column_span": 4,
                "cards": [d["detail"]],
            }],
        })

    # ---- 差分 + 持久化 ----
    state.prune({d["area_id"] for d in devices if d.get("area_id")},
                {d["device_id"] for d in devices})
    state.save()

    # 缺图型号清单：供「自动补图」流程消费
    missing = sorted({d["model"] for d in devices if not d["card"].get("image")})
    try:
        json.dump(missing, open(MISSING_FILE, "w"), ensure_ascii=False, indent=1)
    except Exception as e:  # noqa: BLE001
        print("写缺图清单失败:", e)

    out = {"views": views}
    json.dump(out, open(OUT_FILE, "w"), ensure_ascii=False, indent=1)
    print("devices:", len(devices), "views:", len(views))
    for aid in sorted(groups.keys(), key=area_sort_key):
        items = groups[aid]["items"]
        meta = area_meta.get(aid)
        tail = f"  [/{meta['slug']}]" if meta else ""
        print(f"  {groups[aid]['name']}: {len(items)}{tail} -> {[i['name'] for i in items]}")
    print("with photo:", sum(1 for d in devices if d["card"].get("image")))
    print("no photo:", missing)
    print("--- 变更 ---")
    print(state.report())


if __name__ == "__main__":
    main()
