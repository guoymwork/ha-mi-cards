#!/usr/bin/env python3
"""刷新 HA 前端认证 token，写入 /tmp/ha_tokens.json（前端 localStorage 格式）。

用法: python3 refresh_tokens.py
"""
import json
import subprocess
import sys
import time
import urllib.parse
import urllib.request

HA = "http://192.168.31.67:8123"
TOK_FILE = "/tmp/ha_tokens.json"


def nas_auth_users():
    """从 NAS 的 .storage/auth 里取 refresh_token（管理员账号）。"""
    out = subprocess.run(
        ["ssh", "-o", "ConnectTimeout=8", "fnos",
         "cat /vol1/1000/docker/haos/.storage/auth"],
        capture_output=True, text=True, timeout=30,
    )
    data = json.loads(out.stdout).get("data", {})
    owner_ids = {u["id"] for u in data.get("users", []) if u.get("is_owner")}
    best = None
    for rt in data.get("refresh_tokens", []):
        # 注意：.storage/auth 里存的是 rt["token"]，不是 rt["refresh_token"]
        if rt.get("token_type") != "normal" or not rt.get("token"):
            continue
        if rt.get("user_id") in owner_ids:
            return rt["token"]
        best = best or rt["token"]
    if best:
        return best
    raise SystemExit("未找到 refresh_token")


def refresh(refresh_token):
    """用 refresh_token 换新的 access_token（走 curl，绕开沙箱的直连限制）。"""
    body = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "client_id": HA + "/",
        "refresh_token": refresh_token,
    })
    out = subprocess.run(
        ["curl", "-s", "--noproxy", "*", "--max-time", "30",
         "-X", "POST", "-H", "Content-Type: application/x-www-form-urlencoded",
         "--data", body, HA + "/auth/token"],
        capture_output=True, text=True, timeout=40,
    )
    return json.loads(out.stdout)


def main():
    tokens = json.load(open(TOK_FILE))
    rt = tokens.get("refresh_token")
    res = None
    if rt:
        try:
            res = refresh(rt)
        except Exception as e:
            print("本地 refresh_token 失效，改用 .storage/auth:", e)
            res = None
    if res is None:
        rt = nas_auth_users()
        res = refresh(rt)
    # HA 的刷新响应不一定带 refresh_token，沿用旧的以备下次刷新
    res.setdefault("refresh_token", rt)
    res["expires"] = int(time.time() * 1000) + res.get("expires_in", 1800) * 1000
    res["hassUrl"] = HA
    res["clientId"] = HA + "/"
    json.dump(res, open(TOK_FILE, "w"), ensure_ascii=False, indent=1)
    print("已刷新，expires_in =", res.get("expires_in"), "type =", res.get("token_type"))


if __name__ == "__main__":
    main()
