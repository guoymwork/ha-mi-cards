"""产品图管理：米家百科抓取 + 标准化 + 型号→URL 映射。

对应外部脚本 ``fetch_raw_images.py`` + ``normalize_images.py``，
但完全跑在 HA 进程内：不需要 SSH、不需要令牌、不需要外部机器。

产物落在 ``<config>/www/mi_cards/images/``，HA 的 frontend 组件把
``<config>/www`` 映射到 ``/local``，所以成品图直接以
``/local/mi_cards/images/xxx.png?v=<hash>`` 引用即可。

原始图保留在 ``<config>/mi_cards/raw/``，重新标准化时不必再联网抓一次。
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import urllib.parse
from pathlib import Path
from typing import Any, Iterable

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store

from .const import (
    BAIKE_API,
    BAIKE_REFERER,
    BAIKE_USER_AGENT,
    DATA_DIR_NAME,
    DOMAIN,
    IMAGES_DIR_NAME,
)

_LOGGER = logging.getLogger(__name__)

try:  # Pillow 是 HA 运行时自带依赖（requirements_all: Pillow==13.0.0）
    from PIL import Image

    try:
        _RESAMPLE = Image.Resampling.LANCZOS
    except AttributeError:  # pragma: no cover - 老版本 Pillow
        _RESAMPLE = Image.LANCZOS
except ImportError:  # pragma: no cover - 理论不会发生
    Image = None  # type: ignore[assignment]
    _RESAMPLE = None  # type: ignore[assignment]

# --- 标准化参数（与 normalize_images.py 保持一致）---
CANVAS = 480  # 输出画布边长
FILL = 0.86  # 主体长边占画布比例
WIDE_RATIO = 2.0  # 宽高比超过此值视为「横向长条」（空调/机顶盒等）
WIDE_FILL = 0.92  # 横向长条按宽度归一
MIN_CONTENT = 12  # 主体小于该像素数视为空图，不处理

# HA 型号百科查不到时借用的收录型号
BAIKE_ALIAS: dict[str, str] = {
    "roborock.vacuum.a134": "roborock.vacuum.p5",
    "roborock.vacuum.a134 Dock": "roborock.vacuum.p5",
}

_HEADERS = {
    "Referer": BAIKE_REFERER,
    "User-Agent": BAIKE_USER_AGENT,
    "Accept": "*/*",
}

# 抓取节奏
_FETCH_CONCURRENCY = 3
_FETCH_DELAY = 0.25
_FETCH_TIMEOUT = aiohttp.ClientTimeout(total=40)
_FETCH_RETRIES = 4
_FETCH_BACKOFF = 1.5


def safe(model: str) -> str:
    """型号转文件名。"""
    return model.replace(".", "_").replace(" ", "_")


def _content_bbox(im) -> tuple[int, int, int, int] | None:
    """返回主体的 alpha 包围盒；无有效 alpha 时退化为「非近白像素」包围盒。"""
    alpha = im.getchannel("A")
    bb = alpha.getbbox()
    if bb and (bb[2] - bb[0]) >= MIN_CONTENT and (bb[3] - bb[1]) >= MIN_CONTENT:
        return bb
    rgb = im.convert("RGB")
    w, h = rgb.size
    px = rgb.load()
    xs: list[int] = []
    ys: list[int] = []
    step = max(1, min(w, h) // 160)
    for y in range(0, h, step):
        for x in range(0, w, step):
            r, g, b = px[x, y]
            if not (r > 242 and g > 242 and b > 242):
                xs.append(x)
                ys.append(y)
    if not xs:
        return None
    return (min(xs), min(ys), max(xs) + 1, max(ys) + 1)


def _normalize_file(path: Path) -> str:
    """把图片标准化到统一画布，返回描述文本。线程内执行。"""
    if Image is None:  # pragma: no cover
        raise RuntimeError("Pillow 不可用，无法标准化图片")
    im = Image.open(path).convert("RGBA")
    bb = _content_bbox(im)
    if not bb:
        return "空图，跳过"
    crop = im.crop(bb)
    cw, ch = crop.size
    ratio = max(cw, ch) / max(1, min(cw, ch))
    if ratio > WIDE_RATIO:
        # 横向长条（空调/机顶盒）：按宽度归一，否则在方盒里只剩细细一条
        nw = int(CANVAS * WIDE_FILL)
        nh = max(1, round(ch * nw / cw))
    else:
        side = int(CANVAS * FILL)
        scale = side / max(cw, ch)
        nw, nh = max(1, round(cw * scale)), max(1, round(ch * scale))
    crop = crop.resize((nw, nh), _RESAMPLE)
    canvas = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    canvas.paste(crop, ((CANVAS - nw) // 2, (CANVAS - nh) // 2), crop)
    canvas.save(path, "PNG", optimize=True)
    return "%dx%d -> 主体 %dx%d%s" % (
        im.size[0],
        im.size[1],
        nw,
        nh,
        " (横向按宽归一)" if ratio > WIDE_RATIO else "",
    )


class ImageManager:
    """管理米家百科产品图的抓取、标准化与 URL 映射。"""

    def __init__(self, hass: HomeAssistant) -> None:
        """初始化。"""
        self.hass = hass
        self._store = Store(hass, 1, f"{DOMAIN}_images")
        # model -> {"file": "xxx.png", "v": "内容哈希"}
        self._entries: dict[str, dict[str, str]] = {}
        self._lock = asyncio.Lock()

    # ---------- 路径 ----------

    @property
    def images_dir(self) -> Path:
        """成品目录（被 HA 的 /local 暴露）。"""
        return Path(self.hass.config.path("www", DATA_DIR_NAME, IMAGES_DIR_NAME))

    @property
    def raw_dir(self) -> Path:
        """原始图目录（保留，便于重新标准化而不必重抓）。"""
        return Path(self.hass.config.path(DATA_DIR_NAME, "raw"))

    # ---------- 持久化 ----------

    async def async_load(self) -> None:
        """从存储读取映射，并剔除文件已丢失的条目。"""
        data = await self._store.async_load()
        entries: dict[str, dict[str, str]] = {}
        if isinstance(data, dict):
            for model, val in data.items():
                if isinstance(val, dict) and val.get("file"):
                    entries[model] = {
                        "file": val["file"],
                        "v": str(val.get("v") or ""),
                    }
        # 文件被手动删掉的条目要同步清掉，否则会指向 404
        alive = {
            m: e
            for m, e in entries.items()
            if (self.images_dir / e["file"]).is_file()
        }
        if len(alive) != len(entries):
            _LOGGER.debug("清理 %d 条图片映射（文件已不存在）", len(entries) - len(alive))
            self._entries = alive
            await self._store.async_save(self._entries)
        else:
            self._entries = alive

    async def _async_save(self) -> None:
        """保存映射。"""
        await self._store.async_save(self._entries)

    # ---------- 查询 ----------

    def url_for(self, model: str) -> str | None:
        """按型号取成品图 URL。"""
        entry = self._entries.get(model)
        if not entry:
            return None
        if not (self.images_dir / entry["file"]).is_file():
            return None
        return "/local/%s/%s/%s?v=%s" % (
            DATA_DIR_NAME,
            IMAGES_DIR_NAME,
            entry["file"],
            entry["v"] or "0",
        )

    def image_map(self) -> dict[str, str]:
        """型号 → URL 的完整映射，供设备树使用。"""
        out: dict[str, str] = {}
        for model in self._entries:
            url = self.url_for(model)
            if url:
                out[model] = url
        return out

    def missing_models(self, models: Iterable[str]) -> list[str]:
        """哪些型号还没有成品图。"""
        return [m for m in models if not self.url_for(m)]

    def status(self) -> dict[str, Any]:
        """给配置流/服务用的状态摘要。"""
        return {
            "cached": len(self._entries),
            "dir": str(self.images_dir),
            "models": sorted(self._entries),
        }

    # ---------- 抓取 ----------

    async def _async_baike(self, model: str) -> tuple[str | None, str | None, bool]:
        """查百科，返回 (产品名, 实物图 URL, 请求是否成功)。

        请求成功但 code != 0 表示「百科未收录」；请求失败则第三项为 False。
        """
        url = BAIKE_API.format(urllib.parse.quote(model))
        payload = await self._async_get_json(url)
        if not isinstance(payload, dict):
            return None, None, False
        if payload.get("code") != 0:
            return None, None, True
        data = payload.get("data") or {}
        return data.get("name"), data.get("realIcon"), True

    async def _async_get_json(self, url: str) -> Any:
        """GET 一个 JSON，失败自动重试（米家 CDN 偶发断连）。"""
        session = async_get_clientsession(self.hass)
        for attempt in range(_FETCH_RETRIES):
            try:
                async with session.get(
                    url, headers=_HEADERS, timeout=_FETCH_TIMEOUT
                ) as resp:
                    if resp.status != 200:
                        return None
                    try:
                        return await resp.json(content_type=None)
                    except (aiohttp.ContentTypeError, ValueError):
                        return None
            except (aiohttp.ClientError, asyncio.TimeoutError):
                if attempt < _FETCH_RETRIES - 1:
                    await asyncio.sleep(_FETCH_BACKOFF * (attempt + 1))
        return None

    async def _async_download(self, url: str) -> bytes | None:
        """下载原始图，失败自动重试。"""
        session = async_get_clientsession(self.hass)
        for attempt in range(_FETCH_RETRIES):
            try:
                async with session.get(
                    url, headers=_HEADERS, timeout=_FETCH_TIMEOUT
                ) as resp:
                    if resp.status != 200:
                        return None
                    return await resp.read()
            except (aiohttp.ClientError, asyncio.TimeoutError):
                if attempt < _FETCH_RETRIES - 1:
                    await asyncio.sleep(_FETCH_BACKOFF * (attempt + 1))
        return None

    async def _async_fetch_one(self, model: str, force: bool) -> tuple[str, str]:
        """抓单个型号的成品图，返回 (status, message)。

        status: ok / skip / miss / error
        """
        entry = self._entries.get(model)
        if entry and not force and (self.images_dir / entry["file"]).is_file():
            return "skip", "已有"

        name, icon, reachable = await self._async_baike(model)
        lookup = model
        if not icon:
            alias = BAIKE_ALIAS.get(model)
            if alias:
                name, icon, _ = await self._async_baike(alias)
                if icon:
                    lookup = alias
        if not icon:
            if not reachable:
                return "error", "百科请求失败（已重试 %d 次）" % _FETCH_RETRIES
            return "miss", "百科未收录"

        raw_name = safe(lookup) + ".png"
        raw_path = self.raw_dir / raw_name
        out_path = self.images_dir / raw_name

        if force or not raw_path.is_file():
            try:
                raw = await self._async_download(icon)
            except (aiohttp.ClientError, asyncio.TimeoutError) as err:
                return "error", "下载失败: %s" % err
            if not raw:
                return "error", "下载失败（重试 %d 次仍失败）" % _FETCH_RETRIES
            if raw[:4] != b"\x89PNG":
                return "error", "百科图不是 PNG"
            await self.hass.async_add_executor_job(
                _write_bytes, raw_path, raw
            )

        if out_path.is_file() and not force:
            return "skip", "已有"

        await self.hass.async_add_executor_job(_copy_normalize, raw_path, out_path)

        digest = await self.hass.async_add_executor_job(_file_hash, out_path)
        self._entries[model] = {"file": raw_name, "v": digest}
        return "ok", "%s -> %s" % (name or lookup, raw_name)

    async def async_sync(
        self,
        models: Iterable[str],
        force: bool = False,
    ) -> dict[str, Any]:
        """同步一批型号的产品图。

        并发抓取（限流 3），已有跳过。返回统计结果。
        """
        uniq: list[str] = []
        seen: set[str] = set()
        for m in models:
            if m and m not in seen:
                seen.add(m)
                uniq.append(m)
        if not uniq:
            return {"total": 0, "ok": 0, "skip": 0, "miss": 0, "error": 0, "details": []}

        self.images_dir.mkdir(parents=True, exist_ok=True)
        self.raw_dir.mkdir(parents=True, exist_ok=True)

        sem = asyncio.Semaphore(_FETCH_CONCURRENCY)
        details: list[dict[str, str]] = []

        async def _run(model: str) -> None:
            async with sem:
                if _FETCH_DELAY:
                    await asyncio.sleep(_FETCH_DELAY)
                try:
                    status, msg = await self._async_fetch_one(model, force)
                except Exception as err:  # noqa: BLE001
                    status, msg = "error", str(err)
                details.append({"model": model, "status": status, "message": msg})
                if status == "ok":
                    _LOGGER.debug("产品图 %s: %s", model, msg)

        async with self._lock:
            await asyncio.gather(*(_run(m) for m in uniq))
            await self._async_save()

        counts = {"ok": 0, "skip": 0, "miss": 0, "error": 0}
        for d in details:
            counts[d["status"]] = counts.get(d["status"], 0) + 1
        counts["total"] = len(uniq)
        counts["details"] = details
        return counts


# ---------- 线程内小工具 ----------


def _write_bytes(path: Path, data: bytes) -> None:
    """写文件（线程内）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    if data:
        path.write_bytes(data)
    elif not path.exists():
        path.touch()


def _copy_normalize(src: Path, dst: Path) -> None:
    """复制原图到成品目录并标准化（线程内）。"""
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(src.read_bytes())
    _normalize_file(dst)


def _file_hash(path: Path) -> str:
    """文件内容哈希（线程内），用于破缓存。"""
    return hashlib.sha1(path.read_bytes()).hexdigest()[:10]
