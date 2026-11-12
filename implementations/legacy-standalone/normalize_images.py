#!/usr/bin/env python3
"""标准化米家百科产品图：裁掉多余留白 -> 等比缩放 -> 居中放入统一画布。

背景：百科 realIcon 是 480x480，但每个型号的「主体占比」差异极大
（实测 31% ~ 100%），直接放进卡片会出现「空调是一条线、插头却撑满」
的视觉失衡。这里统一裁到主体并居中放在 480x480 透明画布上，
主体长边统一占 86%，于是所有设备图在卡片里的视觉大小一致。

原图永远不动：标准化结果写入「输出目录」，可反复重跑。

用法：
    ./normalize_images.py                          # 原图库 -> 成品库
    ./normalize_images.py --src A --out B
    ./normalize_images.py --nas fnos:/path/to/www/mi-images   # 同步到远端
    ./normalize_images.py --only-new                # 只处理成品库里还没有的
"""

import argparse
import glob
import os
import shutil
import subprocess
import sys

from PIL import Image

CANVAS = 480          # 输出画布边长
FILL = 0.86           # 主体长边占画布比例
WIDE_RATIO = 2.0      # 宽高比超过此值视为「横向长条」（空调/机顶盒等）
WIDE_FILL = 0.92      # 横向长条按宽度归一
MIN_CONTENT = 12      # 主体小于该像素数视为空图，不处理


def content_bbox(im):
    """返回主体的 alpha 包围盒；无有效 alpha 时退化为「非近白像素」包围盒。"""
    alpha = im.getchannel("A")
    bb = alpha.getbbox()
    if bb and (bb[2] - bb[0]) >= MIN_CONTENT and (bb[3] - bb[1]) >= MIN_CONTENT:
        return bb
    rgb = im.convert("RGB")
    w, h = rgb.size
    px = rgb.load()
    xs, ys = [], []
    step = max(1, min(w, h) // 160)
    for y in range(0, h, step):
        for x in range(0, w, step):
            r, g, b = px[x, y]
            if not (r > 242 and g > 242 and b > 242):
                xs.append(x)
                ys.append(y)
    if not xs:
        return None
    return (min(xs), min(ys), max(xs) + 1, max(ys) + 1)


def normalize(path):
    im = Image.open(path).convert("RGBA")
    bb = content_bbox(im)
    if not bb:
        return False, "空图，跳过"
    crop = im.crop(bb)
    cw, ch = crop.size
    ratio = max(cw, ch) / max(1, min(cw, ch))
    if ratio > WIDE_RATIO:
        # 横向长条（空调/机顶盒）：按宽度归一，否则在方盒里只剩细细一条
        nw = int(CANVAS * WIDE_FILL)
        nh = max(1, round(ch * nw / cw))
    else:
        side = int(CANVAS * FILL)
        scale = side / max(cw, ch)
        nw, nh = max(1, round(cw * scale)), max(1, round(ch * scale))
    crop = crop.resize((nw, nh), Image.LANCZOS)
    canvas = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    canvas.paste(crop, ((CANVAS - nw) // 2, (CANVAS - nh) // 2), crop)
    canvas.save(path, "PNG", optimize=True)
    return True, "%dx%d -> 主体 %dx%d%s" % (
        im.size[0], im.size[1], nw, nh, " (横向按宽归一)" if ratio > WIDE_RATIO else "")


def sync_nas(spec, out_dir, files):
    """把成品图同步到远端 www 目录。spec 形如 host:/remote/dir"""
    if not spec or ":" not in spec:
        return False
    host, remote = spec.split(":", 1)
    for f in files:
        subprocess.run(["scp", "-q", "-o", "ConnectTimeout=10", f,
                        "%s:%s/%s" % (host, remote, os.path.basename(f))], check=False)
    # HAOS 的 www 实际目录与 /config/www 是软链/绑定关系，两处都放一份
    subprocess.run(["ssh", "-o", "ConnectTimeout=10", host,
                    "cp -f %s/*.png /tmp/mi-images/ 2>/dev/null || true" % remote],
                   check=False, capture_output=True)
    return True


def main():
    ap = argparse.ArgumentParser(description="标准化米家百科产品图")
    ap.add_argument("--src", default=os.environ.get("MI_RAW_DIR", "/tmp/mi-img-raw"),
                    help="原始库目录")
    ap.add_argument("--out", default=os.environ.get("MI_IMG_DIR", "/tmp/mi-img-work"),
                    help="成品库目录")
    ap.add_argument("--nas", default=os.environ.get("MI_IMG_NAS", ""),
                    help="同步目标，形如 host:/remote/dir")
    ap.add_argument("--only-new", action="store_true", help="只处理成品库里还没有的")
    args = ap.parse_args()

    files = sorted(glob.glob(os.path.join(args.src, "*.png")))
    if not files:
        print("原图目录里没有 PNG: %s" % args.src)
        return 1
    os.makedirs(args.out, exist_ok=True)

    todo = []
    for f in files:
        dst = os.path.join(args.out, os.path.basename(f))
        if args.only_new and os.path.exists(dst):
            continue
        todo.append((f, dst))

    print("标准化 %d/%d 张图片（主体长边统一占 %.0f%%）"
          % (len(todo), len(files), FILL * 100))
    for f, dst in todo:
        try:
            shutil.copyfile(f, dst)          # 原图不动，标准化只作用于副本
            ok, msg = normalize(dst)
        except Exception as e:  # noqa: BLE001
            print("  ! %-34s %s" % (os.path.basename(f), e))
            continue
        print("  %s %-34s %s" % ("v" if ok else "x", os.path.basename(f), msg))

    if args.nas:
        produced = [os.path.join(args.out, os.path.basename(f)) for f, _ in todo]
        if produced:
            sync_nas(args.nas, args.out, produced)
            print("\n已同步 %d 张到 %s" % (len(produced), args.nas))
    else:
        print("\n成品目录: %s（未指定 --nas，未同步远端）" % args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
