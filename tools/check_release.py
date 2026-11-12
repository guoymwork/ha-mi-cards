#!/usr/bin/env python3
"""CI 守卫：确保 HACS 发布镜像（仓库根 custom_components/）与源码真身保持一致。

HACS 只会读取仓库根的 custom_components/，而本仓库的源码真身在
implementations/ha-integration/ 下。两者一旦漂移，HACS 用户拿到的代码就与
仓库里的「真实实现」不一致 —— 这是最容易被忽略的发布事故。

用法：
    python3 tools/check_release.py          # CI 入口，漂移时退出码 1
    python3 tools/check_release.py --quiet   # 只在失败时输出
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sync_release import SOURCE_DIR, TARGET_DIR, diff  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="校验 HACS 发布镜像一致性")
    parser.add_argument("--quiet", action="store_true", help="只在失败时输出")
    args = parser.parse_args()

    if not SOURCE_DIR.exists():
        print(f"✗ 源码目录不存在: {SOURCE_DIR}", file=sys.stderr)
        return 2

    only_source, only_target, different = diff()

    if only_source or only_target or different:
        print("✗ HACS 发布镜像与源码真身不一致：", file=sys.stderr)
        for rel in only_source:
            print(f"  + 仅真身有: {rel}", file=sys.stderr)
        for rel in only_target:
            print(f"  - 仅镜像有: {rel}", file=sys.stderr)
        for rel in different:
            print(f"  ! 内容不同: {rel}", file=sys.stderr)
        print("\n请运行: python3 tools/sync_release.py", file=sys.stderr)
        return 1

    if not args.quiet:
        print("✓ HACS 发布镜像与源码真身一致")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
