#!/usr/bin/env python3
"""把 HA 集成方案（implementations/ha-integration/）的源码同步到仓库根的 HACS 发布镜像。

为什么需要这个脚本
------------------
HACS 对「仓库根即集成」的集成有硬性路径要求：集成代码必须位于
``<repo-root>/custom_components/<domain>/``。而本仓库把两套实现分文件夹存放
（implementations/ha-integration 与 implementations/legacy-standalone），
集成源码的真身就在 implementations 下面，直接发布 HACS 是识别不到的。

于是约定：

    implementations/ha-integration/custom_components/mi_cards/   <- 源码真身（改这里）
    <repo-root>/custom_components/mi_cards/                     <- 发布镜像（由本脚本生成）

发布流程：

    python3 tools/sync_release.py            # 同步
    python3 tools/sync_release.py --check    # 只校验，不写入（CI 用）

镜像目录禁止手工编辑：CI 的 tools/check_release.py 会在检测到漂移时让流水线失败。
"""

from __future__ import annotations

import argparse
import filecmp
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIR = REPO_ROOT / "implementations" / "ha-integration" / "custom_components" / "mi_cards"
TARGET_DIR = REPO_ROOT / "custom_components" / "mi_cards"

EXCLUDE_DIRS = {"__pycache__", ".pytest_cache", ".mypy_cache"}
EXCLUDE_SUFFIXES = {".pyc", ".pyo"}


def _iter_files(root: Path) -> list[Path]:
    """列出目录下所有需要同步的文件（相对路径，已排序）。"""
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel_parts = path.relative_to(root).parts
        if any(part in EXCLUDE_DIRS for part in rel_parts):
            continue
        if path.suffix in EXCLUDE_SUFFIXES:
            continue
        if path.name == ".DS_Store":
            continue
        files.append(path.relative_to(root))
    return sorted(files)


def diff() -> tuple[list[str], list[str], list[str]]:
    """比对真身与镜像，返回 (仅真身有, 仅镜像有, 内容不同)。"""
    only_source: list[str] = []
    only_target: list[str] = []
    different: list[str] = []

    src_files = set(_iter_files(SOURCE_DIR))
    tgt_files = set(_iter_files(TARGET_DIR)) if TARGET_DIR.exists() else set()

    for rel in sorted(src_files - tgt_files):
        only_source.append(str(rel))
    for rel in sorted(tgt_files - src_files):
        only_target.append(str(rel))
    for rel in sorted(src_files & tgt_files):
        s = SOURCE_DIR / rel
        t = TARGET_DIR / rel
        if not filecmp.cmp(s, t, shallow=False):
            different.append(str(rel))

    return only_source, only_target, different


def sync() -> None:
    TARGET_DIR.parent.mkdir(parents=True, exist_ok=True)
    if TARGET_DIR.exists():
        shutil.rmtree(TARGET_DIR)
    shutil.copytree(
        SOURCE_DIR,
        TARGET_DIR,
        ignore=shutil.ignore_patterns(*EXCLUDE_DIRS, "*.pyc", "*.pyo", ".DS_Store"),
    )
    count = len(_iter_files(TARGET_DIR))
    print(f"✓ 已同步 {count} 个文件 -> {TARGET_DIR.relative_to(REPO_ROOT)}/")


def main() -> int:
    parser = argparse.ArgumentParser(description="同步 HACS 发布镜像")
    parser.add_argument("--check", action="store_true", help="只校验不写入，漂移时退出码 1")
    args = parser.parse_args()

    if not SOURCE_DIR.exists():
        print(f"✗ 源码目录不存在: {SOURCE_DIR}", file=sys.stderr)
        return 2

    if args.check:
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
        print("✓ HACS 发布镜像与源码真身一致")
        return 0

    sync()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
