#!/usr/bin/env python3
"""仓库结构与规范自检。

在提交前跑一遍，把最容易出问题的几类问题挡在本地：

    python3 tools/check.py

检查项
------
1. 集成目录是否齐全（manifest / config_flow / const / services.yaml / strings.json / translations）
2. manifest 必填字段与键序（hassfest 对自定义集成的强制要求）
3. 所有 JSON 文件可解析
4. 敏感信息扫描：内网 IP、凭据关键字、私人路径
5. 资源缓存版本号：const.py 的 VERSION 与 manifest.json 的 version 是否一致

退出码：0 = 全部通过，1 = 有问题。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
INTEGRATION = REPO_ROOT / "custom_components" / "mi_cards"

REQUIRED_FILES = [
    "__init__.py",
    "config_flow.py",
    "const.py",
    "device_tree.py",
    "images.py",
    "manifest.json",
    "services.yaml",
    "strings.json",
    "static/mi-cards.js",
    "translations/en.json",
    "translations/zh-Hans.json",
]

# manifest 必填字段（hassfest 对 custom integration 的强制要求）
MANIFEST_REQUIRED = ["domain", "name", "codeowners", "requirements", "version", "iot_class"]

# 敏感信息扫描规则：(正则, 说明)
SECRET_PATTERNS = [
    (re.compile(r"/vol\d+/"), "疑似私人 NAS 路径"),
    (re.compile(r"\bpassword\s*=\s*['\"][^'\"]+['\"]", re.I), "硬编码密码"),
    (re.compile(r"\bpasswd\s*=\s*['\"][^'\"]+['\"]", re.I), "硬编码密码"),
    (re.compile(r"\bsecret\s*=\s*['\"][^'\"]+['\"]", re.I), "硬编码密钥"),
    (re.compile(r"\bapi[_-]?key\s*=\s*['\"][^'\"]+['\"]", re.I), "硬编码 API Key"),
    (re.compile(r"\bBearer\s+[A-Za-z0-9._\-]{20,}"), "疑似 Bearer 令牌"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"), "疑似 GitHub 令牌"),
    (re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"), "疑似 JWT"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "私钥"),
]

# IP 地址单独处理（要排除回环地址与版本号形态）
IP_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
IP_ALLOWED = {"127.0.0.1", "0.0.0.0", "255.255.255.255", "localhost"}

# 允许出现 IP 的文件（文档里用来举例说明，非真实凭据）
SCAN_SKIP_DIRS = {".git", "__pycache__", ".venv", "node_modules"}
SCAN_SKIP_SUFFIXES = {".zip", ".png", ".jpg", ".jpeg", ".webp", ".pyc"}

problems: list[str] = []
notes: list[str] = []


def fail(msg: str) -> None:
    problems.append(msg)


def _suspicious_ip(line: str) -> str | None:
    """返回行内第一个可疑 IP，回环地址与版本号形态不算。"""
    for m in IP_RE.finditer(line):
        ip = m.group(0)
        if ip in IP_ALLOWED:
            continue
        parts = ip.split(".")
        # 版本号形态（如 120.0.0.0）不是地址
        if parts[2] == "0" and parts[3] == "0" and int(parts[0]) > 1:
            continue
        return ip
    return None


def scan_secrets() -> None:
    """扫描仓库里的疑似敏感信息。"""
    for path in REPO_ROOT.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(REPO_ROOT)
        if any(part in SCAN_SKIP_DIRS for part in rel.parts):
            continue
        if path.suffix in SCAN_SKIP_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            ip = _suspicious_ip(line)
            if ip:
                fail(f"{rel}:{lineno} 疑似内网/真实 IP 地址（{ip}）-> {line.strip()[:80]}")
            for pattern, desc in SECRET_PATTERNS:
                if pattern.search(line):
                    fail(f"{rel}:{lineno} {desc} -> {line.strip()[:80]}")


def main() -> int:
    # ---------------------------------------------------------- 1. 文件齐全
    missing = [f for f in REQUIRED_FILES if not (INTEGRATION / f).exists()]
    for f in missing:
        fail(f"缺少集成文件：custom_components/mi_cards/{f}")
    if not missing:
        notes.append(f"集成文件齐全（{len(REQUIRED_FILES)} 个）")

    # ---------------------------------------------------------- 2. manifest
    manifest_path = INTEGRATION / "manifest.json"
    manifest: dict = {}
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as err:
            fail(f"manifest.json 解析失败：{err}")
        else:
            for key in MANIFEST_REQUIRED:
                if key not in manifest:
                    fail(f"manifest.json 缺少必填字段：{key}")
            if list(manifest)[:2] != ["domain", "name"]:
                fail("manifest.json 键序必须是 domain, name 开头，然后字母序")
            else:
                notes.append(f"manifest 规范 OK（domain={manifest['domain']} version={manifest['version']}）")

    # ------------------------------------------------------- 3. JSON 全部可解析
    json_files = sorted(REPO_ROOT.rglob("*.json"))
    bad = 0
    for f in json_files:
        if any(part in SCAN_SKIP_DIRS for part in f.relative_to(REPO_ROOT).parts):
            continue
        try:
            json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError as err:
            fail(f"{f.relative_to(REPO_ROOT)} JSON 解析失败：{err}")
            bad += 1
    if not bad:
        notes.append(f"JSON 全部可解析（{len(json_files)} 个）")

    # ------------------------------------------------- 4. 敏感信息扫描
    scan_secrets()

    # ------------------------------------------ 5. 版本号一致性（资源缓存键）
    const_path = INTEGRATION / "const.py"
    if const_path.exists() and manifest:
        const_src = const_path.read_text(encoding="utf-8")
        m = re.search(r'VERSION:\s*Final\s*=\s*"([^"]+)"', const_src)
        if not m:
            fail("const.py 里找不到 VERSION 定义")
        elif m.group(1) != manifest.get("version"):
            fail(
                f"版本号不一致：const.py VERSION={m.group(1)}，"
                f"manifest.json version={manifest.get('version')}"
                "（改了前端 JS 必须同步 bump，否则浏览器拿旧文件）"
            )
        else:
            notes.append(f"版本号一致（{m.group(1)}）")

    # ------------------------------------------------------------- 输出
    for n in notes:
        print(f"✓ {n}")
    if problems:
        print("")
        for p in problems:
            print(f"✗ {p}", file=sys.stderr)
        print(f"\n共 {len(problems)} 个问题", file=sys.stderr)
        return 1
    print("\n✓ 全部检查通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
