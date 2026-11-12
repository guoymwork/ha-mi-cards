#!/usr/bin/env python3
"""真实改名端到端测试：在 HA 里改房间名 -> 同步 -> 验证 URL 是否还活着。"""
import json
import os
import sys
import time

sys.path.insert(0, "/tmp/mi-cards")
from ha_ws import HAWS  # noqa: E402

TOKEN = open("/tmp/mi-cards/ha_token.txt").read().strip()


def ws():
    w = HAWS(host="127.0.0.1", port=8123, token=TOKEN)
    w.handshake()
    return w


def sync():
    env = dict(os.environ)
    env.update({
        "MI_WORK_DIR": "/tmp/mi-cards",
        "MI_TOKEN_FILE": "/tmp/mi-cards/ha_token.txt",
        "MI_IMG_DIRS": "/vol1/1000/docker/haos/www/mi-images",
        "MI_WWW_DIR": "/vol1/1000/docker/haos/www",
        "MI_STATE_FILE": "/vol1/1000/docker/haos/.mi-cards/state.json",
    })
    import subprocess
    p = subprocess.run([sys.executable, "/tmp/mi-cards/sync.py", "--stage", "all"],
                       env=env, capture_output=True, text=True)
    return p.stdout + p.stderr


def views():
    w = ws()
    cfg = w.command("lovelace/config", {"url_path": "device-cards"}) or {}
    w.sock.close()
    return cfg.get("views") or []


w = ws()
areas = w.command("config/area_registry/list") or []
target = next((a for a in areas if a.get("name") == "客厅"), None)
if not target:
    print("找不到「客厅」区域")
    sys.exit(1)
old_name = target["name"]
area_id = target.get("area_id") or target.get("id")
print("原区域名:", old_name, "| area_id:", area_id)

before = {v.get("path"): v.get("title") for v in views() if not v.get("subview")}
print("改名前区域视图:", {k: v for k, v in before.items() if k})

# ---- 改名 ----
print("\n>>> 在 HA 里把「客厅」改名为「起居室」")
w.command("config/area_registry/update", {"area_id": area_id, "name": "起居室"})
w.sock.close()
time.sleep(2)

log = sync()
print(log[log.find("--- 变更 ---"):][:600] if "--- 变更 ---" in log else log[-600:])

after = {v.get("path"): v.get("title") for v in views() if not v.get("subview")}
print("改名后区域视图:", after)

print("\n>>> 结论")
old_path = None
for p, t in before.items():
    if t == old_name:
        old_path = p
new_title = after.get(old_path)
print(f"  原路径 /{old_path}  ->  现在标题: {new_title}")
if new_title == "起居室":
    print("  ✅ 改名后链接仍然有效，标题自动跟随")
else:
    print("  ❌ 链接失效或标题未更新")

# ---- 改回去 ----
print("\n>>> 改回「客厅」")
w = ws()
w.command("config/area_registry/update", {"area_id": area_id, "name": old_name})
w.sock.close()
time.sleep(2)
log = sync()
back = {v.get("path"): v.get("title") for v in views() if not v.get("subview")}
print("  改回后:", {k: v for k, v in back.items() if k == old_path})
print(f"  {'✅' if back.get(old_path) == old_name else '❌'} 已还原")
