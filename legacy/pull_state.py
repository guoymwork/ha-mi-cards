#!/usr/bin/env python3
"""从 HA 拉取设备状态与注册表快照，供 gen_dashboard.py 生成面板配置。

输出（目录由 MI_WORK_DIR 决定，默认 /tmp）:
  ha_states.json      全部实体状态（list 格式）
  ha_registries.json  实体/设备/区域注册表

用法:
  python3 pull_state.py
  环境变量:
    MI_WORK_DIR  工作目录（默认 /tmp）
    MI_TOKEN_FILE  token 文件（默认 $MI_WORK_DIR/ha_token.txt）
    MI_HA_HOST / MI_HA_PORT  HA 地址（默认 127.0.0.1:8123）
"""
import json
import os
import sys
import time

WORK = os.environ.get("MI_WORK_DIR") or "/tmp"
TOKEN_FILE = os.environ.get("MI_TOKEN_FILE") or os.path.join(WORK, "ha_token.txt")
HOST = os.environ.get("MI_HA_HOST") or "127.0.0.1"
PORT = int(os.environ.get("MI_HA_PORT") or 8123)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ha_ws import HAWS  # noqa: E402


def connect(host, port, token, retries=6):
    """HA 偶尔会直接关掉刚建立的 WS（限流/负载高），重试几次即可。"""
    last = None
    for i in range(retries):
        try:
            ws = HAWS(host=host, port=port, token=token)
            ws.handshake()
            return ws
        except Exception as e:  # noqa: BLE001
            last = e
            print("  连接重试(%d/%d): %s" % (i + 1, retries, e))
            time.sleep(2 + i)
    raise SystemExit("无法连接 HA: %s" % last)


def main():
    if not os.path.exists(TOKEN_FILE):
        raise SystemExit("找不到 token 文件: %s" % TOKEN_FILE)
    token = open(TOKEN_FILE).read().strip()
    ws = connect(HOST, PORT, token)

    states = ws.command("get_states")
    json.dump(states, open(os.path.join(WORK, "ha_states.json"), "w"), ensure_ascii=False)

    reg = {
        "entity_registry": {"entities": ws.command("config/entity_registry/list")},
        "device_registry": {"devices": ws.command("config/device_registry/list")},
        "area_registry": {"areas": ws.command("config/area_registry/list")},
    }
    json.dump(reg, open(os.path.join(WORK, "ha_registries.json"), "w"), ensure_ascii=False)

    print("states:", len(states),
          "| entities:", len(reg["entity_registry"]["entities"]),
          "| devices:", len(reg["device_registry"]["devices"]),
          "| areas:", len(reg["area_registry"]["areas"]))
    ws.sock.close()


if __name__ == "__main__":
    main()
