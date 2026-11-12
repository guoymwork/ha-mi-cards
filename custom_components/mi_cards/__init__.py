"""米家风格设备面板 —— Home Assistant 自定义集成。

把原来「外部 Python 脚本 + SSH + 令牌 + 定时任务」整套流程搬进 HA 进程内：

* 设备树：直接读 entity / device / area 注册表（``device_tree.build_device_tree``）
* 产品图：在 HA 内抓米家百科并用 Pillow 标准化（``images.ImageManager``）
* 面板：直接写 Lovelace 存储模式面板，房间/设备变化时自动重建
* 前端：集成自带 ``static/mi-cards.js``，注册成 Lovelace 资源后即可用

安装即用，不需要任何外部机器。
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

import probatio

from homeassistant.components import frontend, websocket_api
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import CoreState, HomeAssistant, ServiceCall, callback
from homeassistant.helpers.area_registry import EVENT_AREA_REGISTRY_UPDATED
from homeassistant.helpers.device_registry import EVENT_DEVICE_REGISTRY_UPDATED
from homeassistant.helpers.entity_registry import EVENT_ENTITY_REGISTRY_UPDATED
from homeassistant.helpers.typing import ConfigType

from .const import (
    CARD_JS_URL,
    CARD_TYPE_WALL,
    CONF_ACCENT,
    CONF_AUTO_SYNC_IMAGES,
    CONF_DASHBOARD_TITLE,
    CONF_DASHBOARD_URL,
    CONF_SHOW_IN_SIDEBAR,
    DEFAULT_ACCENT,
    DEFAULT_DASHBOARD_TITLE,
    DEFAULT_DASHBOARD_URL,
    DEFAULT_SIDEBAR_ICON,
    DOMAIN,
    EVENT_TREE_UPDATED,
    NAME,
    TREE_CACHE_TTL,
    VERSION,
    WS_TYPE_DEVICE_TREE,
)
from .device_tree import build_device_tree
from .images import ImageManager

_LOGGER = logging.getLogger(__name__)

_STATIC_DIR = Path(__file__).parent / "static"

# 旧版外部脚本资源（/local/mi-cards.js），集成接管后清理掉
_LEGACY_RESOURCE_PREFIX = "/local/mi-cards.js"


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """YAML 入口（本集成只走 UI 配置流）。"""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """配置流入口。"""
    data = hass.data.setdefault(DOMAIN, {})

    # ---------- 产品图管理器 ----------
    images = ImageManager(hass)
    await images.async_load()
    data["images"] = images
    data["entry"] = entry

    # ---------- 前端静态资源 ----------
    if not data.get("static_ready"):
        await hass.http.async_register_static_paths(
            [StaticPathConfig(CARD_JS_URL.rsplit("/", 1)[0], str(_STATIC_DIR), False)]
        )
        data["static_ready"] = True

    # ---------- WebSocket 命令 ----------
    websocket_api.async_register_command(hass, ws_device_tree)

    # ---------- Lovelace 资源 ----------
    await _async_register_resource(hass)

    # ---------- 面板 ----------
    # 设备树依赖 hass.states，而集成 setup 早于其它集成创建实体，
    # 所以要等 homeassistant_started 之后再写面板，否则会写出一份空视图。
    _schedule_initial_dashboard(hass, entry)

    # ---------- 注册表变化 -> 设备树更新推送 ----------
    unsub_listeners = [
        hass.bus.async_listen(event, _make_registry_listener(hass))
        for event in (
            EVENT_AREA_REGISTRY_UPDATED,
            EVENT_DEVICE_REGISTRY_UPDATED,
            EVENT_ENTITY_REGISTRY_UPDATED,
        )
    ]
    data["unsub"] = unsub_listeners

    # ---------- 服务 ----------
    hass.services.async_register(DOMAIN, "sync_images", _async_service_sync_images)
    hass.services.async_register(DOMAIN, "refresh", _async_service_refresh)

    # ---------- 配置变更后重新生成面板 ----------
    entry.async_on_unload(entry.add_update_listener(_async_entry_updated))

    # ---------- 自动补图 ----------
    if entry.options.get(CONF_AUTO_SYNC_IMAGES, entry.data.get(CONF_AUTO_SYNC_IMAGES, True)):
        hass.async_create_task(_async_auto_sync_images(hass))

    _LOGGER.info("%s %s 已就绪", NAME, VERSION)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """卸载配置流。"""
    data = hass.data.get(DOMAIN, {})
    for unsub in data.pop("unsub", []):
        unsub()
    for key in ("dash_timer", "dash_retry"):
        cancel = data.pop(key, None)
        if cancel is not None:
            cancel()
    hass.services.async_remove(DOMAIN, "sync_images")
    hass.services.async_remove(DOMAIN, "refresh")
    data.pop("images", None)
    data.pop("tree", None)
    data.pop("tree_at", None)
    return True


# ---------------------------------------------------------------- 设备树


def _accent(entry: ConfigEntry | None) -> str:
    """取主色。"""
    if entry is None:
        return DEFAULT_ACCENT
    return entry.options.get(CONF_ACCENT) or entry.data.get(CONF_ACCENT) or DEFAULT_ACCENT


def _dashboard_url(entry: ConfigEntry | None) -> str:
    """取面板 URL 路径。"""
    if entry is None:
        return DEFAULT_DASHBOARD_URL
    return (
        entry.options.get(CONF_DASHBOARD_URL)
        or entry.data.get(CONF_DASHBOARD_URL)
        or DEFAULT_DASHBOARD_URL
    )


def _dashboard_title(entry: ConfigEntry | None) -> str:
    """取面板标题。"""
    if entry is None:
        return DEFAULT_DASHBOARD_TITLE
    return (
        entry.options.get(CONF_DASHBOARD_TITLE)
        or entry.data.get(CONF_DASHBOARD_TITLE)
        or DEFAULT_DASHBOARD_TITLE
    )


def _show_in_sidebar(entry: ConfigEntry | None) -> bool:
    """面板是否显示在侧边栏。"""
    if entry is None:
        return True
    return bool(
        entry.options.get(
            CONF_SHOW_IN_SIDEBAR, entry.data.get(CONF_SHOW_IN_SIDEBAR, True)
        )
    )


def _invalidate_tree(hass: HomeAssistant) -> None:
    """设备树缓存失效。"""
    hass.data.get(DOMAIN, {})["tree"] = None


def _build_tree(hass: HomeAssistant) -> dict[str, Any]:
    """构建（或取缓存）设备树。"""
    data = hass.data.setdefault(DOMAIN, {})
    now = time.monotonic()
    cached = data.get("tree")
    if cached is not None and (now - data.get("tree_at", 0.0)) < TREE_CACHE_TTL:
        return cached

    images: ImageManager | None = data.get("images")
    image_map = images.image_map() if images else None
    entry: ConfigEntry | None = data.get("entry")
    tree = build_device_tree(hass, image_map=image_map, accent=_accent(entry))
    data["tree"] = tree
    data["tree_at"] = now
    return tree


@callback
def _make_registry_listener(hass: HomeAssistant):
    """注册表变化监听器：让前端知道要重新拉设备树，并重算面板视图。"""

    def _listener(event) -> None:
        _invalidate_tree(hass)
        hass.bus.async_fire(EVENT_TREE_UPDATED, {"changed": event.data.get("action", "")})
        _schedule_dashboard_update(hass)

    return _listener


def _schedule_initial_dashboard(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """等实体就绪后再生成面板。"""
    data = hass.data.setdefault(DOMAIN, {})

    async def _write(_event=None) -> None:
        await _async_write_dashboard(hass, entry)
        if _has_devices(hass):
            cancel = data.pop("dash_retry", None)
            if cancel is not None:
                cancel()
            return
        # 还没扫到设备，稍后再试
        if data.get("dash_retry") is not None:
            return
        data["dash_retry"] = hass.async_call_later(
            30, lambda: hass.async_create_task(_write())
        )

    if hass.state is CoreState.running:
        hass.async_create_task(_write())
    else:
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _write)


def _schedule_dashboard_update(hass: HomeAssistant) -> None:
    """注册表变化后防抖重算面板（房间/设备增减会改变视图列表）。"""
    data = hass.data.setdefault(DOMAIN, {})
    cancel = data.pop("dash_timer", None)
    if cancel is not None:
        cancel()
    entry: ConfigEntry | None = data.get("entry")
    if entry is None:
        return

    def _run(_now) -> None:
        hass.async_create_task(_async_write_dashboard(hass, entry))

    data["dash_timer"] = hass.async_call_later(3, _run)


def _has_devices(hass: HomeAssistant) -> bool:
    """当前设备树里是否已经有设备。"""
    tree = hass.data.get(DOMAIN, {}).get("tree") or {}
    return bool(tree.get("devices"))


@websocket_api.websocket_command({probatio.Required("type"): WS_TYPE_DEVICE_TREE})
@websocket_api.async_response
async def ws_device_tree(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """返回整棵设备树。"""
    tree = _build_tree(hass)
    connection.send_result(msg["id"], tree)


# ---------------------------------------------------------------- 面板


def _build_dashboard_config(tree: dict[str, Any], accent: str) -> dict[str, Any]:
    """按设备树生成 Lovelace 面板配置。

    布局沿用实测可用结构：``type: sections`` 视图 + 一个 ``grid`` section，
    ``max_columns=4`` 配 ``column_span=4`` 让 section 铺满内容区整宽。
    卡片内部自己排网格，所以 section 里只放一张区域墙卡片。

    一个「全部」视图 + 每个区域一个视图 —— 区域分类放在 HA 原生顶部二级菜单里。
    """

    def _wall(**extra: Any) -> dict[str, Any]:
        card: dict[str, Any] = {"type": CARD_TYPE_WALL, "accent": accent}
        card.update(extra)
        return {"type": "grid", "column_span": 4, "cards": [card]}

    views: list[dict[str, Any]] = [
        {
            "type": "sections",
            "title": "全部",
            "path": "all",
            "icon": "mdi:home-outline",
            "show_icon_and_title": True,
            "max_columns": 4,
            "sections": [_wall(show_tabs=False, show_area=True)],
        }
    ]

    used = {"all"}
    for area in tree.get("areas") or []:
        path = area.get("slug") or area.get("id") or "area"
        base = path
        idx = 2
        while path in used:
            path = f"{base}-{idx}"
            idx += 1
        used.add(path)
        views.append(
            {
                "type": "sections",
                "title": area.get("name") or path,
                "path": path,
                "icon": area.get("icon") or "mdi:sofa",
                "show_icon_and_title": True,
                "max_columns": 4,
                "sections": [_wall(area=area.get("id"), show_area=False)],
            }
        )

    if tree.get("other"):
        path = "other"
        idx = 2
        while path in used:
            path = f"other-{idx}"
            idx += 1
        used.add(path)
        views.append(
            {
                "type": "sections",
                "title": "其他",
                "path": path,
                "icon": "mdi:dots-horizontal",
                "show_icon_and_title": True,
                "max_columns": 4,
                "sections": [_wall(area="other", show_area=False)],
            }
        )

    return {"views": views}


async def _async_write_dashboard(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """创建/更新 Lovelace 面板。"""
    from homeassistant.components.lovelace.const import LOVELACE_DATA
    from homeassistant.components.lovelace.dashboard import LovelaceStorage

    url_path = _dashboard_url(entry)
    title = _dashboard_title(entry)
    accent = _accent(entry)
    # 面板是低频操作，强制重算一次设备树，保证拿到最新状态
    _invalidate_tree(hass)
    tree = _build_tree(hass)
    if not tree.get("devices"):
        # 实体还没就绪，先不覆盖已有面板
        _LOGGER.debug("设备树暂无设备，跳过面板更新")
        return
    config = _build_dashboard_config(tree, accent)

    dashboards = hass.data[LOVELACE_DATA].dashboards
    dash = dashboards.get(url_path)
    owned_by_lovelace = dash is not None

    if dash is None:
        dash = LovelaceStorage(
            hass, {"id": url_path.replace("-", "_"), "url_path": url_path}
        )
        dashboards[url_path] = dash

    # 已有配置且完全一致就不写盘，避免无谓的前端刷新
    current: Any = None
    try:
        current = await dash.async_load(False)
    except Exception:  # noqa: BLE001 - 配置不存在是正常情况
        current = None
    if current != config:
        await dash.async_save(config)
        _LOGGER.debug("面板 %s 已更新（%d 个视图）", url_path, len(config["views"]))

    # 面板注册：lovelace 自己管的（存在于 lovelace_dashboards 存储）就不抢
    if not owned_by_lovelace and not frontend.async_panel_exists(hass, url_path):
        frontend.async_register_built_in_panel(
            hass,
            "lovelace",
            frontend_url_path=url_path,
            sidebar_title=title,
            sidebar_icon=DEFAULT_SIDEBAR_ICON,
            require_admin=False,
            show_in_sidebar=_show_in_sidebar(entry),
            config={"mode": "storage"},
        )


# ---------------------------------------------------------------- 资源


async def _async_ensure_loaded(collection: Any) -> None:
    """确保集合已从存储加载。"""
    ensure = getattr(collection, "_async_ensure_loaded", None)
    if ensure is not None:
        await ensure()
    elif not getattr(collection, "loaded", False):
        await collection.async_load()


async def _async_register_resource(hass: HomeAssistant) -> None:
    """把前端 JS 注册成 Lovelace 资源。"""
    from homeassistant.components.lovelace.const import LOVELACE_DATA

    resources = hass.data[LOVELACE_DATA].resources
    await _async_ensure_loaded(resources)

    url = f"{CARD_JS_URL}?v={VERSION}"

    # 清理旧版外部脚本资源，避免重复加载与 404
    for item in list(resources.async_items()):
        item_url = str(item.get("url") or "")
        if item_url.split("?")[0] == _LEGACY_RESOURCE_PREFIX:
            try:
                await resources.async_delete_item(item["id"])
                _LOGGER.info("已移除旧版资源 %s", item_url)
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("移除旧资源失败: %s", err)

    existing = None
    for item in resources.async_items():
        if str(item.get("url") or "").split("?")[0] == CARD_JS_URL:
            existing = item
            break

    if existing is None:
        await resources.async_create_item({"res_type": "module", "url": url})
        _LOGGER.info("已注册 Lovelace 资源 %s", url)
    elif existing.get("url") != url:
        await resources.async_update_item(existing["id"], {"url": url})
        _LOGGER.info("已更新 Lovelace 资源 %s", url)


# ---------------------------------------------------------------- 服务


def _collect_models(hass: HomeAssistant) -> list[str]:
    """扫描全部设备型号。"""
    from homeassistant.helpers import device_registry as dr

    dev_reg = dr.async_get(hass)
    models: list[str] = []
    for device in dev_reg.devices:
        model = device.model or ""
        if not model or "." not in model:
            continue
        if model.split(".")[0] == "integration":
            continue
        if model not in models:
            models.append(model)
    return models


async def _async_auto_sync_images(hass: HomeAssistant) -> None:
    """开机后自动补齐缺失的产品图。"""
    images: ImageManager | None = hass.data.get(DOMAIN, {}).get("images")
    if images is None:
        return
    models = _collect_models(hass)
    missing = images.missing_models(models)
    if not missing:
        return
    _LOGGER.info("自动补图：%d 个型号缺图", len(missing))
    await images.async_sync(missing)
    _invalidate_tree(hass)


async def _async_service_sync_images(hass: HomeAssistant, call: ServiceCall) -> None:
    """服务 mi_cards.sync_images：抓取/标准化产品图。"""
    images: ImageManager | None = hass.data.get(DOMAIN, {}).get("images")
    if images is None:
        _LOGGER.warning("集成尚未就绪")
        return
    models = call.data.get("models") or _collect_models(hass)
    force = bool(call.data.get("force", False))
    result = await images.async_sync(models, force=force)
    _invalidate_tree(hass)
    _LOGGER.info(
        "产品图同步完成：共 %s，成功 %s，跳过 %s，未收录 %s，失败 %s",
        result.get("total"),
        result.get("ok"),
        result.get("skip"),
        result.get("miss"),
        result.get("error"),
    )


async def _async_entry_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """配置变更后重新生成面板。"""
    _invalidate_tree(hass)
    await _async_write_dashboard(hass, entry)


async def _async_service_refresh(hass: HomeAssistant, call: ServiceCall) -> None:
    """服务 mi_cards.refresh：重建设备树并重新生成面板。"""
    entry: ConfigEntry | None = hass.data.get(DOMAIN, {}).get("entry")
    _invalidate_tree(hass)
    if entry is not None:
        await _async_write_dashboard(hass, entry)
    hass.bus.async_fire(EVENT_TREE_UPDATED, {"changed": "refresh"})
