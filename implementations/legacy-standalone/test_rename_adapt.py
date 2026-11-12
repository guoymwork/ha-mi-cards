#!/usr/bin/env python3
"""验证「房间/设备改名后 URL 不失效、图标自动跟随」。

做法：在假的注册表快照上模拟改名/增删，再跑生成器，比对前后差异。
"""
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
GEN = os.path.join(HERE, "gen_dashboard.py")


def run(state_file, reg_file):
    env = dict(os.environ)
    env["MI_STATE_FILE"] = state_file
    env["MI_MISSING_FILE"] = "/tmp/mi-missing-test.json"
    # 用改过的注册表快照跑
    src = open(GEN, encoding="utf-8").read()
    patched = src.replace('"/tmp/ha_registries.json"', json.dumps(reg_file))
    patched = patched.replace('"/tmp/ha_states.json"', '"/tmp/ha_states.json"')
    tmp = os.path.join(HERE, "_gen_test_tmp.py")
    open(tmp, "w", encoding="utf-8").write(patched)
    out = subprocess.run([sys.executable, tmp], capture_output=True, text=True, env=env)
    if out.returncode != 0:
        print(out.stdout[-2000:], out.stderr[-2000:])
        raise SystemExit("生成失败")
    return out.stdout


def views_of():
    c = json.load(open("/tmp/device_dashboard.json"))
    return c["views"]


def areas_of(views):
    return {v["title"]: (v.get("path"), v.get("icon"))
            for v in views if not v.get("subview")}


def devices_of(views):
    return {v["title"]: v.get("path")
            for v in views if v.get("subview")}


REG = json.load(open("/tmp/ha_registries.json"))
STATE = "/tmp/state-rename-test.json"

print("=" * 64)
print("场景 1：首次生成")
print("=" * 64)
if os.path.exists(STATE):
    os.remove(STATE)
run(STATE, "/tmp/ha_registries.json")
v1 = views_of()
a1, d1 = areas_of(v1), devices_of(v1)
print("区域视图:")
for k, (p, ic) in a1.items():
    print(f"  {k:<10} path=/{p:<12} icon={ic}")

print("\n" + "=" * 64)
print("场景 2：把「客厅」改名为「起居室」，把「P20 Pro」改名为「石头扫地机」")
print("=" * 64)
reg2 = json.loads(json.dumps(REG))
for a in reg2["area_registry"]["areas"]:
    if a.get("name") == "客厅":
        a["name"] = "起居室"
for d in reg2["device_registry"]["devices"]:
    if d.get("name") == "P20 Pro":
        d["name_by_user"] = "石头扫地机"
json.dump(reg2, open("/tmp/reg2.json", "w"), ensure_ascii=False)

log = run(STATE, "/tmp/reg2.json")
v2 = views_of()
a2, d2 = areas_of(v2), devices_of(v2)

print("变更报告:")
for line in log.split("--- 变更 ---")[-1].strip().splitlines():
    print(" ", line.strip())

print("\n区域 URL 对比（path 应保持不变，只有 title 和 icon 跟随）:")
ok = True
for name_old in a1:
    name_new = "起居室" if name_old == "客厅" else name_old
    p_old, i_old = a1[name_old]
    p_new, i_new = a2.get(name_new, (None, None))
    same = "OK " if p_old == p_new else "FAIL"
    if p_old != p_new:
        ok = False
    print(f"  {same} {name_old:<10} -> {name_new:<10} /{p_old} -> /{p_new}   icon {i_old} -> {i_new}")

print("\n设备详情页 URL 对比:")
for name_old in d1:
    name_new = "石头扫地机" if name_old == "P20 Pro" else name_old
    p_old = d1[name_old]
    p_new = d2.get(name_new)
    same = "OK " if p_old == p_new else "FAIL"
    if p_old != p_new:
        ok = False
    print(f"  {same} {name_old:<16} -> {name_new:<16} /{p_old} -> /{p_new}")

print("\n" + "=" * 64)
print("场景 3：新建 UUID 区域「衣帽间」，并把「路灯」挪进去")
print("=" * 64)
reg3 = json.loads(json.dumps(reg2))
reg3["area_registry"]["areas"].append({
    "area_id": "3f9a1c22-7b41-4e88-9a01-2c3d4e5f6a7b", "name": "衣帽间",
})
for d in reg3["device_registry"]["devices"]:
    if d.get("name") == "路灯":
        d["area_id"] = "3f9a1c22-7b41-4e88-9a01-2c3d4e5f6a7b"
json.dump(reg3, open("/tmp/reg3.json", "w"), ensure_ascii=False)
log = run(STATE, "/tmp/reg3.json")
v3 = views_of()
a3 = areas_of(v3)
print("变更报告:")
for line in log.split("--- 变更 ---")[-1].strip().splitlines():
    print(" ", line.strip())
print("\n新区域视图:", a3.get("衣帽间"))
print("路灯是否已从庭院移出:", "庭院" in a3)

print("\n" + "=" * 64)
print("场景 4：删除「衣帽间」区域及其中的设备")
print("=" * 64)
reg4 = json.loads(json.dumps(reg3))
reg4["area_registry"]["areas"] = [a for a in reg4["area_registry"]["areas"]
                                 if a.get("name") != "衣帽间"]
reg4["device_registry"]["devices"] = [d for d in reg4["device_registry"]["devices"]
                                      if d.get("name") != "路灯"]
json.dump(reg4, open("/tmp/reg4.json", "w"), ensure_ascii=False)
log = run(STATE, "/tmp/reg4.json")
v4 = views_of()
a4 = areas_of(v4)
print("变更报告:")
for line in log.split("--- 变更 ---")[-1].strip().splitlines():
    print(" ", line.strip())
print("衣帽间视图是否已移除:", "衣帽间" not in a4)

print("\n" + "=" * 64)
print("最终结论：", "全部通过 ✅" if ok else "存在失效 ❌")
print("=" * 64)
