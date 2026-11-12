"""Constants for the Mi Cards integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "mi_cards"
NAME: Final = "米家风格设备面板"
VERSION: Final = "1.1.0"

# 前端卡片资源：注册到 /api/mi_cards_static/ 下，由 Lovelace 作为 module 资源加载
STATIC_URL_BASE: Final = "/api/mi_cards_static"
CARD_JS_NAME: Final = "mi-cards.js"
CARD_JS_URL: Final = f"{STATIC_URL_BASE}/{CARD_JS_NAME}"

# 设备树 WebSocket 命令
WS_TYPE_DEVICE_TREE: Final = "mi_cards/device_tree"

# 设备树变更时广播的事件（前端订阅后自动重建）
EVENT_TREE_UPDATED: Final = "mi_cards/tree_updated"

# 数据目录
DATA_DIR_NAME: Final = "mi_cards"
IMAGES_DIR_NAME: Final = "images"

# 卡片类型
CARD_TYPE_WALL: Final = "custom:mi-device-wall"
CARD_TYPE_DEVICE: Final = "custom:mi-device-card"
CARD_TYPE_DETAIL: Final = "custom:mi-device-detail"

# 默认面板 URL 路径
DEFAULT_DASHBOARD_URL: Final = "device-cards"
DEFAULT_ACCENT: Final = "#ff6a00"
DEFAULT_DASHBOARD_TITLE: Final = "设备"
DEFAULT_SIDEBAR_ICON: Final = "mdi:home-assistant"

# 配置项
CONF_DASHBOARD_URL: Final = "dashboard_url"
CONF_DASHBOARD_TITLE: Final = "dashboard_title"
CONF_ACCENT: Final = "accent"
CONF_SHOW_IN_SIDEBAR: Final = "show_in_sidebar"
CONF_AUTO_SYNC_IMAGES: Final = "auto_sync_images"
CONF_AREA: Final = "area"

# 设备树缓存有效期（秒）。注册表变化会立即失效，此值只是兜底。
TREE_CACHE_TTL: Final = 30.0

# 米家产品百科接口
BAIKE_API: Final = "https://home.mi.com/cgi-op/api/v1/baike/v2/product?model={}"
BAIKE_REFERER: Final = "https://home.mi.com/webapp/content/baike/product/index.html"
BAIKE_USER_AGENT: Final = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
