#!/usr/bin/env python3
"""在 NAS 上临时改「设备」总览视图的 sections 参数并回读，用于实测宽度配比。

用法: python3 try_section_width.py <max_columns> <column_span>
"""
import json
import sys
import time

sys.path.insert(0, "/tmp")
from ha_ws import HAWS  # noqa: E402

TOKEN = open("/tmp/ha_token.txt").read().strip()
MAXC = int(sys.argv[1])
SPAN = int(sys.argv[2])

ws = None
for _ in range(5):
    try:
        ws = HAWS(host="127.0.0.1", port=8123, token=TOKEN)
        ws.handshake()
        break
    except Exception:
        time.sleep(2)

cfg = ws.command("lovelace/config", {"url_path": "device-cards"})
v = cfg["views"][0]
v["max_columns"] = MAXC
v["sections"][0]["column_span"] = SPAN
ws.command("lovelace/config/save", {"url_path": "device-cards", "config": cfg})
print(f"已应用 max_columns={MAXC} column_span={SPAN}")
ws.sock.close()
