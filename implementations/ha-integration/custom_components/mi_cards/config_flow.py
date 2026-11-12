"""米家风格设备面板 的配置流。

注意（2026.11 / probatio）：配置流的 data_schema 必须能被
``probatio.to_field_list`` 序列化成前端字段，所以字段类型只能用
``str`` / ``bool`` 这类可识别类型，**不能**放自定义校验函数
（否则直接抛 ``ValueError: unable to serialize schema``，配置流直接 500）。
自定义校验放到流程里做。
"""

from __future__ import annotations

from typing import Any

import probatio

from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import callback

from .const import (
    CONF_ACCENT,
    CONF_AUTO_SYNC_IMAGES,
    CONF_DASHBOARD_TITLE,
    CONF_DASHBOARD_URL,
    CONF_SHOW_IN_SIDEBAR,
    DEFAULT_ACCENT,
    DEFAULT_DASHBOARD_TITLE,
    DEFAULT_DASHBOARD_URL,
    DOMAIN,
    NAME,
)


def _defaults(source: ConfigEntry | None = None) -> dict[str, Any]:
    """默认值（可从已有配置继承）。"""
    if source is None:
        return {
            CONF_DASHBOARD_URL: DEFAULT_DASHBOARD_URL,
            CONF_DASHBOARD_TITLE: DEFAULT_DASHBOARD_TITLE,
            CONF_ACCENT: DEFAULT_ACCENT,
            CONF_SHOW_IN_SIDEBAR: True,
            CONF_AUTO_SYNC_IMAGES: True,
        }
    data = {**source.data, **source.options}
    return {
        CONF_DASHBOARD_URL: data.get(CONF_DASHBOARD_URL, DEFAULT_DASHBOARD_URL),
        CONF_DASHBOARD_TITLE: data.get(CONF_DASHBOARD_TITLE, DEFAULT_DASHBOARD_TITLE),
        CONF_ACCENT: data.get(CONF_ACCENT, DEFAULT_ACCENT),
        CONF_SHOW_IN_SIDEBAR: data.get(CONF_SHOW_IN_SIDEBAR, True),
        CONF_AUTO_SYNC_IMAGES: data.get(CONF_AUTO_SYNC_IMAGES, True),
    }


def _schema(defaults: dict[str, Any]) -> probatio.Schema:
    """生成配置表单 schema（字段类型必须可序列化）。"""
    return probatio.Schema(
        {
            probatio.Optional(
                CONF_DASHBOARD_URL, default=defaults[CONF_DASHBOARD_URL]
            ): str,
            probatio.Optional(
                CONF_DASHBOARD_TITLE, default=defaults[CONF_DASHBOARD_TITLE]
            ): str,
            probatio.Optional(CONF_ACCENT, default=defaults[CONF_ACCENT]): str,
            probatio.Optional(
                CONF_SHOW_IN_SIDEBAR, default=defaults[CONF_SHOW_IN_SIDEBAR]
            ): bool,
            probatio.Optional(
                CONF_AUTO_SYNC_IMAGES, default=defaults[CONF_AUTO_SYNC_IMAGES]
            ): bool,
        }
    )


def _validate(user_input: dict[str, Any]) -> dict[str, str]:
    """校验表单内容，返回 {字段: 错误码}（空表示通过）。"""
    errors: dict[str, str] = {}

    url = str(user_input.get(CONF_DASHBOARD_URL) or "").strip().strip("/")
    if not url:
        errors[CONF_DASHBOARD_URL] = "invalid_url"
    elif "-" not in url:
        # HA 的面板路径必须包含连字符
        errors[CONF_DASHBOARD_URL] = "invalid_url"

    accent = str(user_input.get(CONF_ACCENT) or "").strip()
    if not (accent.startswith("#") and len(accent) in (4, 7)):
        errors[CONF_ACCENT] = "invalid_accent"

    if not str(user_input.get(CONF_DASHBOARD_TITLE) or "").strip():
        errors[CONF_DASHBOARD_TITLE] = "invalid_title"

    return errors


def _normalize(user_input: dict[str, Any]) -> dict[str, Any]:
    """规整提交值。"""
    out = dict(user_input)
    out[CONF_DASHBOARD_URL] = str(
        user_input.get(CONF_DASHBOARD_URL) or ""
    ).strip().strip("/")
    out[CONF_DASHBOARD_TITLE] = str(user_input.get(CONF_DASHBOARD_TITLE) or "").strip()
    out[CONF_ACCENT] = str(user_input.get(CONF_ACCENT) or "").strip()
    out[CONF_SHOW_IN_SIDEBAR] = bool(user_input.get(CONF_SHOW_IN_SIDEBAR, True))
    out[CONF_AUTO_SYNC_IMAGES] = bool(user_input.get(CONF_AUTO_SYNC_IMAGES, True))
    return out


class MiCardsConfigFlow(ConfigFlow, domain=DOMAIN):
    """处理面板配置。"""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """第一步：基本设置。"""
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        if user_input is not None:
            errors = _validate(user_input)
            if errors:
                defaults = {**_defaults(), **user_input}
                return self.async_show_form(
                    step_id="user",
                    data_schema=_schema(defaults),
                    errors=errors,
                )
            return self.async_create_entry(title=NAME, data=_normalize(user_input))

        return self.async_show_form(step_id="user", data_schema=_schema(_defaults()))

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """返回选项流。"""
        return MiCardsOptionsFlow()


class MiCardsOptionsFlow(OptionsFlow):
    """修改面板设置。"""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """选项表单。"""
        if user_input is not None:
            errors = _validate(user_input)
            if errors:
                defaults = {**_defaults(self.config_entry), **user_input}
                return self.async_show_form(
                    step_id="init",
                    data_schema=_schema(defaults),
                    errors=errors,
                )
            return self.async_create_entry(title="", data=_normalize(user_input))

        return self.async_show_form(
            step_id="init",
            data_schema=_schema(_defaults(self.config_entry)),
        )
