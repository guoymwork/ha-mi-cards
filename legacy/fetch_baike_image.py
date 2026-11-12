#!/usr/bin/env python3
"""从米家产品百科抓取官方实物图，部署到 HA 的 www/mi-images/。

数据源：https://home.mi.com/cgi-op/api/v1/baike/v2/product?model=<型号>
        该接口是米家 App「产品百科」页 (/webapp/content/baike/product/index.html?model=xxx) 的数据源，
        返回 JSON，含 realIcon（480x480 官方产品图，永久签名）与 name（官方品名）。

用法：
    ./fetch_baike_image.py                       # 从 HA 设备注册表自动取全部型号
    ./fetch_baike_image.py zimi.waterheater.h03  # 手动指定型号
"""

import json
import os
import re
import struct
import subprocess
import sys
import time
import urllib.parse
import urllib.request

API = "https://home.mi.com/cgi-op/api/v1/baike/v2/product?model={}"
NAS_HOST = "fnos"
NAS_IMG = "/vol1/1000/docker/haos/www/mi-images"
NAS_TMP_IMG = "/tmp/mi-images"  # 生成器也会扫这个目录
REFERER = "https://home.mi.com/webapp/content/baike/product/index.html"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

# HA 注册型号 -> 百科收录型号（某些设备 HA 型号百科查不到，借用同品牌收录型号的官方图）
BAIKE_ALIAS = {
    # 石头 P20 Pro：HA 型号 roborock.vacuum.a134 百科未收录，
    # 借用百科收录的「石头扫地机器人 P5」官方实物图
    "roborock.vacuum.a134": "roborock.vacuum.p5",
    "roborock.vacuum.a134 Dock": "roborock.vacuum.p5",
}


def http_get(url, timeout=40, binary=False, retries=4):
    """带指数退避重试的 GET（图片 CDN 偶发 SSL 断连）。"""
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"Referer": REFERER, "User-Agent": UA})
            with _opener.open(req, timeout=timeout) as r:
                data = r.read()
            return data if binary else data.decode("utf-8", "replace")
        except Exception as e:
            last = e
            if attempt < retries - 1:
                time.sleep(1.5 * (attempt + 1))
    raise last


def baike(model):
    """查询百科接口，返回 (official_name, icon_url) 或 (None, None)。"""
    try:
        d = json.loads(http_get(API.format(urllib.parse.quote(model))))
    except Exception as e:
        print("  ! 请求失败 %s: %s" % (model, e))
        return None, None
    if d.get("code") != 0:
        return None, None
    data = d.get("data") or {}
    return data.get("name"), data.get("realIcon")

def png_size(path):
    with open(path, "rb") as f:
        head = f.read(24)
    if head[:4] != b"\x89PNG":
        return None
    w, h = struct.unpack(">II", head[16:24])
    return w, h


def safe(model):
    return model.replace(".", "_")


def fetch(model):
    # 先按原型号查百科；查不到再试别名型号（图片按实际命中的型号命名）
    lookup = model
    name, icon = baike(model)
    if not icon:
        alias = BAIKE_ALIAS.get(model)
        if alias:
            name, icon = baike(alias)
            if icon:
                lookup = alias
                print("    (原型号百科未收录，改用别名 %s)" % alias)
    if not icon:
        print("  x %-30s 百科未收录" % model)
        return False
    out = "/tmp/baike_%s.png" % safe(lookup)
    try:
        raw = http_get(icon, binary=True)
    except Exception as e:
        print("  ! 图片下载失败 %s: %s" % (model, e))
        return False
    if raw[:4] != b"\x89PNG":
        print("  ! %s 返回的不是 PNG" % model)
        return False
    with open(out, "wb") as f:
        f.write(raw)
    w, h = png_size(out)
    fn = "%s.png" % safe(lookup)
    subprocess.run(["scp", "-q", "-o", "ConnectTimeout=10", out,
                    "%s:%s/%s" % (NAS_HOST, NAS_IMG, fn)], check=True)
    # 生成器同时扫描 /tmp/mi-images，用 ssh 复制过去（scp 直传该目录权限受限）
    subprocess.run(["ssh", "-o", "ConnectTimeout=10", NAS_HOST,
                    "cp -f %s/%s %s/%s 2>/dev/null || true" % (NAS_IMG, fn, NAS_TMP_IMG, fn)],
                   check=False, capture_output=True)
    print("  v %-30s %sx%s  %s -> %s" % (model, w, h, name, fn))
    return True


def models_from_registry():
    """从 NAS 上的 HA 设备注册表提取全部 xiaomi 系设备型号。"""
    try:
        out = subprocess.run(
            ["ssh", "-o", "ConnectTimeout=8", NAS_HOST,
             "cat /tmp/ha_registries.json"],
            capture_output=True, text=True, timeout=40)
        reg = json.loads(out.stdout)
    except Exception as e:
        print("读取注册表失败: %s" % e)
        return []
    devs = (reg.get("device_registry") or {}).get("devices") or []
    models = []
    for d in devs:
        m = d.get("model")
        if m and "." in m and m.split(".")[0] not in ("integration",):
            if m not in models:
                models.append(m)
    return models


def main():
    models = sys.argv[1:] or models_from_registry()
    if not models:
        print("没有可处理的型号")
        return 1
    print("共 %d 个型号，开始从米家百科抓图：" % len(models))
    ok = 0
    for i, m in enumerate(models):
        print("[%d/%d] %s" % (i + 1, len(models), m))
        if fetch(m):
            ok += 1
        time.sleep(0.4)
    print("\n成功 %d / %d" % (ok, len(models)))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
