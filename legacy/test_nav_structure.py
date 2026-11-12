#!/usr/bin/env python3
"""测试 HA 顶部视图栏的显示形式：标题 / 图标 / 图标+标题。"""
import json
import sys
import time

sys.path.insert(0, "/tmp")
from ha_ws import HAWS  # noqa: E402

TOKEN = open("/tmp/ha_token.txt").read().strip()


def connect(retries=5):
    for i in range(retries):
        try:
            ws = HAWS(host="127.0.0.1", port=8123, token=TOKEN)
            ws.handshake()
            return ws
        except Exception:
            time.sleep(2)
    raise SystemExit("cannot connect")


def md(text):
    return {"type": "markdown", "content": text}


def main():
    ws = connect()
    for d in ws.command("lovelace/dashboards/list"):
        if d.get("url_path") == "zz-nav-test":
            ws.command("lovelace/dashboards/delete", {"dashboard_id": d["id"]})
            print("deleted old")

    ws.command("lovelace/dashboards/create", {
        "url_path": "zz-nav-test", "title": "NavTest", "mode": "storage",
        "require_admin": False, "show_in_sidebar": True,
    })

    views = [
        {"type": "sections", "title": "全屋", "path": "", "icon": "mdi:home-outline",
         "show_icon_and_title": True,
         "sections": [{"type": "grid", "column_span": 4, "cards": [md("ALL_BODY")]}],
         "badges": []},
        {"type": "sections", "title": "客厅", "path": "a-ting", "icon": "mdi:sofa",
         "show_icon_and_title": True,
         "sections": [{"type": "grid", "column_span": 4, "cards": [md("LIVING_BODY")]}],
         "badges": []},
        {"type": "sections", "title": "厨房", "path": "chu-fang", "icon": "mdi:silverware-fork-knife",
         "show_icon_and_title": True,
         "sections": [{"type": "grid", "column_span": 4, "cards": [md("KITCHEN_BODY")]}],
         "badges": []},
        {"type": "sections", "title": "卧室", "path": "wo-shi", "icon": "mdi:bed-outline",
         "show_icon_and_title": True,
         "sections": [{"type": "grid", "column_span": 4, "cards": [md("BED_BODY")]}],
         "badges": []},
        {"type": "sections", "title": "浴室", "path": "yu-shi", "icon": "mdi:shower",
         "show_icon_and_title": True,
         "sections": [{"type": "grid", "column_span": 4, "cards": [md("BATH_BODY")]}],
         "badges": []},
        {"type": "sections", "title": "庭院", "path": "ting-yuan", "icon": "mdi:tree",
         "show_icon_and_title": True,
         "sections": [{"type": "grid", "column_span": 4, "cards": [md("YARD_BODY")]}],
         "badges": []},
        {"type": "sections", "title": "详情页", "path": "detail-x", "subview": True,
         "sections": [{"type": "grid", "column_span": 4, "cards": [md("SUB_BODY")]}],
         "badges": []},
    ]
    ws.command("lovelace/config/save", {"url_path": "zz-nav-test", "config": {"views": views}})
    print("saved")


if __name__ == "__main__":
    main()
