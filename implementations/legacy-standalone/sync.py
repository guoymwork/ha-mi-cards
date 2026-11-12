#!/usr/bin/env python3
"""设备面板同步器：在 HA 主机上跑的单一入口。

把「拉数据 -> 生成 -> 写配置 -> 破缓存 -> 校验」串成一条命令，
并输出清晰的差分报告（新增/移除/改名的房间与设备）。

用法:
    python3 sync.py --stage snapshot   # 拉状态与注册表快照
    python3 sync.py --stage generate   # 生成配置 + 缺图清单 + 差分报告
    python3 sync.py --stage deploy     # 部署前端资源 + 写入面板配置 + 破缓存
    python3 sync.py --stage verify     # 回读校验（视图/路径/图片可达性）
    python3 sync.py --stage all        # snapshot -> generate -> deploy -> verify

环境变量:
    MI_WORK_DIR      工作目录（默认 /tmp/mi-cards）
    MI_TOKEN_FILE    token 文件
    MI_HA_HOST/PORT  HA 地址
    MI_WWW_DIR       HA 的 www 目录（用于放 mi-cards.js 与图片）
    MI_IMG_DIRS      图片目录（逗号分隔）
    MI_DASH_PATH     面板 URL path
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.environ.get("MI_WORK_DIR") or os.path.join("/tmp", "mi-cards")
TOKEN_FILE = os.environ.get("MI_TOKEN_FILE") or os.path.join(WORK, "ha_token.txt")
HOST = os.environ.get("MI_HA_HOST") or "127.0.0.1"
PORT = int(os.environ.get("MI_HA_PORT") or 8123)
WWW = os.environ.get("MI_WWW_DIR") or "/config/www"
DASH_PATH = os.environ.get("MI_DASH_PATH") or "device-cards"
IMG_DIRS = os.environ.get("MI_IMG_DIRS") or os.path.join(WWW, "mi-images")

sys.path.insert(0, HERE)

ENV = dict(os.environ)
ENV.update({
    "MI_WORK_DIR": WORK,
    "MI_TOKEN_FILE": TOKEN_FILE,
    "MI_HA_HOST": HOST,
    "MI_HA_PORT": str(PORT),
    "MI_IMG_DIRS": IMG_DIRS,
    "MI_DASH_PATH": DASH_PATH,
})


def run(script, *args):
    cmd = [sys.executable, os.path.join(HERE, script)] + list(args)
    p = subprocess.run(cmd, env=ENV)
    if p.returncode != 0:
        raise SystemExit("步骤失败: %s" % script)
    return p.returncode


def stage_snapshot():
    print("==> 拉取 HA 状态与注册表快照")
    run("pull_state.py")


def stage_generate():
    print("==> 生成面板配置")
    run("gen_dashboard.py")


def stage_images():
    """按缺图清单抓取并标准化产品图（尽力而为：缺 Pillow 或没外网就跳过）。"""
    print("==> 补齐产品图")
    missing = os.path.join(WORK, "mi-missing-models.json")
    if not os.path.exists(missing):
        print("  无缺图清单，跳过")
        return
    try:
        with open(missing, encoding="utf-8") as f:
            models = json.load(f) or []
    except Exception:  # noqa: BLE001
        models = []
    if not models:
        print("  所有设备都有产品图")
        return

    try:
        import PIL  # noqa: F401
    except ImportError:
        print("  跳过（本机缺 Pillow：pip3 install Pillow）")
        return

    raw_dir = os.path.join(WORK, "img-raw")
    out_dir = os.path.join(WORK, "img-out")
    try:
        run("fetch_raw_images.py", "--missing", missing, "--out", raw_dir)
        run("normalize_images.py", "--src", raw_dir, "--out", out_dir)
    except SystemExit:
        print("  抓图失败，跳过（不影响面板本体）")
        return

    # 把成品图放进 www 目录
    target = os.path.join(WWW, "mi-images")
    os.makedirs(target, exist_ok=True)
    n = 0
    for fn in os.listdir(out_dir):
        if fn.lower().endswith(".png"):
            shutil.copyfile(os.path.join(out_dir, fn), os.path.join(target, fn))
            n += 1
    print("  已放入 %d 张到 %s" % (n, target))
    # 图片换了版本号，避免浏览器继续用缓存里那张
    ENV["MI_IMG_VER"] = str(int(time.time()))


def stage_deploy():
    print("==> 部署前端资源")
    src = os.path.join(HERE, "mi-cards.js")
    dst = os.path.join(WWW, "mi-cards.js")
    os.makedirs(WWW, exist_ok=True)
    shutil.copyfile(src, dst)
    print("  mi-cards.js -> %s" % dst)

    print("==> 写入面板配置")
    run("deploy_device_dashboard.py")

    print("==> 刷新前端资源版本号（破除浏览器缓存）")
    run("bump_resource_version.py", str(int(time.time())))


def stage_verify():
    print("==> 校验")
    from ha_ws import HAWS  # noqa: E402

    token = open(TOKEN_FILE).read().strip()
    ws = None
    for _ in range(5):
        try:
            ws = HAWS(host=HOST, port=PORT, token=token)
            ws.handshake()
            break
        except Exception:  # noqa: BLE001
            time.sleep(2)
    if ws is None:
        raise SystemExit("无法连接 HA")

    cfg = ws.command("lovelace/config", {"url_path": DASH_PATH}) or {}
    views = cfg.get("views") or []
    print("  回读视图数:", len(views))

    # 路径唯一性
    paths = [v.get("path", "") for v in views]
    dup = {p for p in paths if paths.count(p) > 1}
    print("  重复路径:", dup or "无")

    # 卡片统计 + 图片可达性
    cards = 0
    imgs = set()
    areas = set()
    for v in views:
        for sec in v.get("sections") or []:
            for card in sec.get("cards") or []:
                if card.get("type") == "custom:mi-area-wall":
                    for c in card.get("cards") or []:
                        cards += 1
                        if c.get("image"):
                            imgs.add(c["image"].split("?")[0])
                        if c.get("group"):
                            areas.add(c["group"])
                else:
                    cards += 1
    print("  卡片数:", cards)
    print("  涉及区域:", sorted(areas))

    img_root = os.path.join(WWW, "mi-images")
    missing = []
    for u in sorted(imgs):
        fn = os.path.basename(u)
        if not os.path.exists(os.path.join(img_root, fn)):
            missing.append(fn)
    print("  图片总数:", len(imgs), "| 缺失:", len(missing))
    for m in missing[:10]:
        print("    ! ", m)

    # 详情页 path 与 view path 对应关系
    view_paths = {p for p in paths}
    broken = []
    for v in views:
        for sec in v.get("sections") or []:
            for card in sec.get("cards") or []:
                if card.get("type") == "custom:mi-area-wall":
                    for c in card.get("cards") or []:
                        dp = (c.get("detail_path") or "").lstrip("/")
                        if dp and dp.split("/", 1)[-1] not in view_paths:
                            broken.append(dp)
    print("  详情页链接失效:", len(broken))
    for b in broken[:10]:
        print("    ! ", b)

    ws.sock.close()
    if missing or broken or dup:
        print("\n校验发现问题（详见上面）")
        return 1
    print("\n校验通过 ✅")
    return 0


def main():
    ap = argparse.ArgumentParser(description="设备面板同步器")
    ap.add_argument("--stage", default="all",
                    choices=["snapshot", "generate", "images", "deploy", "verify", "all"])
    args = ap.parse_args()

    os.makedirs(WORK, exist_ok=True)
    stages = {
        "snapshot": [stage_snapshot],
        "generate": [stage_generate],
        "images": [stage_images],
        "deploy": [stage_deploy],
        "verify": [stage_verify],
        "all": [stage_snapshot, stage_generate, stage_images,
                stage_generate, stage_deploy, stage_verify],
    }[args.stage]

    for fn in stages:
        rc = fn()
        if rc:
            raise SystemExit(rc)
    print("\n同步完成")


if __name__ == "__main__":
    main()
