#!/usr/bin/env python3
"""在 HA 上创建「设备」面板并写入 Lovelace 配置。

用法: python3 deploy_device_dashboard.py
环境变量:
  MI_WORK_DIR      工作目录（默认 /tmp）
  MI_TOKEN_FILE    token 文件（默认 $MI_WORK_DIR/ha_token.txt）
  MI_HA_HOST/PORT  HA 地址（默认 127.0.0.1:8123）
  MI_DASH_PATH     面板 URL path（默认 device-cards）
  MI_DASH_TITLE    面板标题（默认 设备）
"""
import json
import os
import sys
import time

WORK = os.environ.get("MI_WORK_DIR") or "/tmp"
TOKEN_FILE = os.environ.get("MI_TOKEN_FILE") or os.path.join(WORK, "ha_token.txt")
HOST = os.environ.get("MI_HA_HOST") or "127.0.0.1"
PORT = int(os.environ.get("MI_HA_PORT") or 8123)
DASH_PATH = os.environ.get("MI_DASH_PATH") or "device-cards"
DASH_TITLE = os.environ.get("MI_DASH_TITLE") or "设备"
CONFIG_FILE = os.path.join(WORK, "device_dashboard.json")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ha_ws import HAWS  # noqa: E402


def connect(token, retries=6):
    """HA 偶尔会直接关掉刚建立的 WS（限流），重试几次即可。"""
    last = None
    for _ in range(retries):
        try:
            ws = HAWS(host=HOST, port=PORT, token=token)
            ws.handshake()
            return ws
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(3)
    raise SystemExit(f"无法连接 HA: {last}")


def main():
    token = open(TOKEN_FILE).read().strip()
    config = json.load(open(CONFIG_FILE))
    ws = connect(token)

    dashboards = ws.command("lovelace/dashboards/list") or []
    target = None
    for d in dashboards:
        if d.get("url_path") == DASH_PATH:
            target = d
    if not target:
        res = ws.command("lovelace/dashboards/create", {
            "title": DASH_TITLE,
            "url_path": DASH_PATH,
            "icon": "mdi:sofa",
            "mode": "storage",
            "require_admin": False,
            "show_in_sidebar": True,
        })
        print("已创建面板:", json.dumps(res, ensure_ascii=False))
    else:
        print("面板已存在:", json.dumps(target, ensure_ascii=False))
        ws.command("lovelace/dashboards/update", {
            "dashboard_id": target["id"],
            "title": DASH_TITLE,
            "icon": "mdi:sofa",
        })

    ws.command("lovelace/config/save", {"url_path": DASH_PATH, "config": config})
    print("配置已保存，视图数:", len(config["views"]))

    # 回读校验
    cfg = ws.command("lovelace/config", {"url_path": DASH_PATH})
    print("回读视图数:", len(cfg.get("views", [])))
    ws.sock.close()


if __name__ == "__main__":
    main()
