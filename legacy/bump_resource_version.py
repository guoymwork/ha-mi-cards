#!/usr/bin/env python3
"""给 lovelace 资源里的 mi-cards.js 加/更新版本参数，破除浏览器 31 天缓存。

用法: python3 bump_resource_version.py <版本号>
环境变量:
  MI_WORK_DIR / MI_TOKEN_FILE / MI_HA_HOST / MI_HA_PORT
  MI_RESOURCE_NAME  资源文件名（默认 mi-cards.js）
"""
import os
import sys
import time

WORK = os.environ.get("MI_WORK_DIR") or "/tmp"
TOKEN_FILE = os.environ.get("MI_TOKEN_FILE") or os.path.join(WORK, "ha_token.txt")
HOST = os.environ.get("MI_HA_HOST") or "127.0.0.1"
PORT = int(os.environ.get("MI_HA_PORT") or 8123)
RESOURCE = os.environ.get("MI_RESOURCE_NAME") or "mi-cards.js"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ha_ws import HAWS  # noqa: E402

VER = sys.argv[1] if len(sys.argv) > 1 else str(int(time.time()))
token = open(TOKEN_FILE).read().strip()

ws = None
for _ in range(5):
    try:
        ws = HAWS(host=HOST, port=PORT, token=token)
        ws.handshake()
        break
    except Exception as e:  # HA 偶发拒绝连接，重试
        print("连接重试:", e)
        time.sleep(2)
if ws is None:
    raise SystemExit("无法连接 HA")

for r in ws.command("lovelace/resources"):
    if RESOURCE in r["url"]:
        base = r["url"].split("?")[0]
        new_url = base + "?v=" + VER
        if new_url == r["url"]:
            print("资源版本号已是最新:", new_url)
        else:
            ws.command("lovelace/resources/update", {"resource_id": r["id"], "url": new_url})
            print("资源版本号已更新 ->", new_url)
        break
else:
    res = ws.command("lovelace/resources/create", {
        "url": "/local/%s?v=%s" % (RESOURCE, VER),
        "type": "module",
    })
    print("资源已创建:", res)

ws.sock.close()
