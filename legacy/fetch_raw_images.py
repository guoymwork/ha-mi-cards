#!/usr/bin/env python3
"""从米家产品百科抓取**原始**实物图到本地原始库。

单独存在的意义：
    标准化脚本 normalize_images.py 会重写图片，而百科原图主体占比差异极大
    （实测 31%~100%），一旦被标准化覆盖就无法还原。
    所以先把原图存到原始库（默认 /tmp/mi-img-raw），再由标准化脚本
    读取原图 -> 处理 -> 输出到成品目录。

增量：原始库里已有的型号默认跳过（--force 可强制重抓）。

用法：
    ./fetch_raw_images.py                        # 从注册表自动取全部型号
    ./fetch_raw_images.py zimi.mosq.v1 ...       # 手动指定型号
    ./fetch_raw_images.py --missing f.json       # 只抓「缺图型号清单」里的
    ./fetch_raw_images.py --registry r.json      # 从本地注册表文件取型号
    ./fetch_raw_images.py --out /tmp/raw         # 指定原始库目录
    ./fetch_raw_images.py --force                # 忽略已有，重新抓
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request

API = "https://home.mi.com/cgi-op/api/v1/baike/v2/product?model={}"
REFERER = "https://home.mi.com/webapp/content/baike/product/index.html"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

# HA 型号百科查不到时借用的收录型号
BAIKE_ALIAS = {
    "roborock.vacuum.a134": "roborock.vacuum.p5",
    "roborock.vacuum.a134 Dock": "roborock.vacuum.p5",
}


def http_get(url, timeout=40, binary=False, retries=4):
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"Referer": REFERER, "User-Agent": UA})
            with _opener.open(req, timeout=timeout) as r:
                data = r.read()
            return data if binary else data.decode("utf-8", "replace")
        except Exception as e:  # noqa: BLE001
            last = e
            if attempt < retries - 1:
                time.sleep(1.5 * (attempt + 1))
    raise last


def baike(model):
    try:
        d = json.loads(http_get(API.format(urllib.parse.quote(model))))
    except Exception as e:  # noqa: BLE001
        print("  ! 请求失败 %s: %s" % (model, e))
        return None, None
    if d.get("code") != 0:
        return None, None
    data = d.get("data") or {}
    return data.get("name"), data.get("realIcon")


def safe(model):
    return model.replace(".", "_")


def fetch(model, raw_dir, force=False):
    lookup = model
    name, icon = baike(model)
    if not icon:
        alias = BAIKE_ALIAS.get(model)
        if alias:
            name, icon = baike(alias)
            if icon:
                lookup = alias
                print("    (原型号未收录，改用别名 %s)" % alias)
    if not icon:
        print("  x %-30s 百科未收录" % model)
        return False
    out = os.path.join(raw_dir, "%s.png" % safe(lookup))
    if os.path.exists(out) and not force:
        print("  - %-30s 已有，跳过" % model)
        return True
    try:
        raw = http_get(icon, binary=True)
    except Exception as e:  # noqa: BLE001
        print("  ! 图片下载失败 %s: %s" % (model, e))
        return False
    if raw[:4] != b"\x89PNG":
        print("  ! %s 不是 PNG" % model)
        return False
    os.makedirs(raw_dir, exist_ok=True)
    with open(out, "wb") as f:
        f.write(raw)
    print("  v %-30s %s -> %s" % (model, name, os.path.basename(out)))
    return True


def models_from_registry(registry_path=None, nas_host=None):
    """从注册表快照提取全部型号（本地文件优先，否则走 SSH 读 NAS 上的）。"""
    reg = None
    if registry_path and os.path.exists(registry_path):
        try:
            reg = json.load(open(registry_path, encoding="utf-8"))
        except Exception:  # noqa: BLE001
            reg = None
    if reg is None and nas_host:
        try:
            out = subprocess.run(["ssh", "-o", "ConnectTimeout=8", nas_host,
                                  "cat /tmp/ha_registries.json"],
                                 capture_output=True, text=True, timeout=40)
            reg = json.loads(out.stdout)
        except Exception as e:  # noqa: BLE001
            print("读取注册表失败: %s" % e)
            return []
    if reg is None:
        print("没有可用的注册表快照（用 --registry 指定）")
        return []
    models = []
    for d in (reg.get("device_registry") or {}).get("devices") or []:
        m = d.get("model")
        if m and "." in m and m.split(".")[0] != "integration" and m not in models:
            models.append(m)
    return models


def models_from_file(path):
    try:
        data = json.load(open(path, encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        print("读不到清单 %s: %s" % (path, e))
        return []
    if isinstance(data, dict):
        data = data.get("models") or data.get("missing") or []
    return [m for m in data if isinstance(m, str) and "." in m]


def main():
    ap = argparse.ArgumentParser(description="抓取米家百科原始产品图")
    ap.add_argument("models", nargs="*", help="手动指定型号（可多个）")
    ap.add_argument("--missing", help="缺图型号清单 JSON（生成器输出）")
    ap.add_argument("--registry", help="注册表快照 JSON 路径")
    ap.add_argument("--out", default=os.environ.get("MI_RAW_DIR", "/tmp/mi-img-raw"),
                    help="原始库目录（默认 /tmp/mi-img-raw）")
    ap.add_argument("--nas-host", default=os.environ.get("MI_NAS_HOST", ""),
                    help="从该主机读注册表（留空则只用 --registry）")
    ap.add_argument("--force", action="store_true", help="已有也重新抓")
    ap.add_argument("--sleep", type=float, default=0.35, help="每次请求间隔秒")
    args = ap.parse_args()

    models = list(args.models)
    if args.missing:
        models += models_from_file(args.missing)
    if not models:
        models = models_from_registry(args.registry, args.nas_host or None)

    # 去重且保持顺序
    seen, uniq = set(), []
    for m in models:
        if m not in seen:
            seen.add(m)
            uniq.append(m)
    if not uniq:
        print("没有可处理的型号")
        return 1

    os.makedirs(args.out, exist_ok=True)
    print("共 %d 个型号，原始库 %s/" % (len(uniq), args.out))
    ok = 0
    for i, m in enumerate(uniq):
        print("[%d/%d] %s" % (i + 1, len(uniq), m))
        if fetch(m, args.out, force=args.force):
            ok += 1
        time.sleep(args.sleep)
    print("\n成功 %d / %d" % (ok, len(uniq)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
