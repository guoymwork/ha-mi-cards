#!/usr/bin/env bash
# 安装本地 git 钩子，在提交/推送前自动做守卫检查。
#
# 为什么需要本地钩子而不是只靠 CI
# -----------------------------
# 本仓库要守的东西：
#   1. 集成结构与 manifest 规范（hassfest 的硬性要求）
#   2. const.py 的 VERSION 与 manifest.json 的 version 一致
#      —— 不一致的话，改了前端 JS 但浏览器拿旧文件
#   3. 仓库里不出现凭据、内网 IP、私人路径
#
# CI 只能在 push 之后才发现；本地 pre-commit 在提交那一刻就拦住，反馈更快，
# 也不需要任何 GitHub 权限。
#
# 用法：
#     bash tools/install_git_hooks.sh
#     bash tools/install_git_hooks.sh --uninstall
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOOKS_DIR="$REPO_ROOT/.git/hooks"

if [ ! -d "$HOOKS_DIR" ]; then
    echo "✗ 不是 git 仓库：$REPO_ROOT" >&2
    exit 1
fi

if [ "${1:-}" = "--uninstall" ]; then
    rm -f "$HOOKS_DIR/pre-commit" "$HOOKS_DIR/pre-push"
    echo "✓ 已移除 pre-commit / pre-push 钩子"
    exit 0
fi

# ---------------------------------------------------------------- pre-commit
cat > "$HOOKS_DIR/pre-commit" <<'HOOK'
#!/usr/bin/env bash
set -euo pipefail
ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

FAILED=0

echo "==> 仓库自检（结构 / manifest / 敏感信息 / 版本一致性）"
if ! python3 tools/check.py; then
    FAILED=1
fi

echo "==> Python 语法检查"
if ! python3 -m py_compile custom_components/mi_cards/*.py tools/*.py; then
    FAILED=1
fi

echo "==> 前端 JS 语法检查"
if command -v node >/dev/null 2>&1; then
    if ! node --check custom_components/mi_cards/static/mi-cards.js; then
        FAILED=1
    fi
else
    echo "  (未安装 node，跳过)"
fi

if [ "$FAILED" -ne 0 ]; then
    echo ""
    echo "✗ 检查未通过，提交被拦截"
    exit 1
fi

echo "✓ 检查通过"
HOOK

# ------------------------------------------------------------------ pre-push
cat > "$HOOKS_DIR/pre-push" <<'HOOK'
#!/usr/bin/env bash
set -euo pipefail
ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

echo "==> 推送前自检"
python3 tools/check.py
HOOK

chmod +x "$HOOKS_DIR/pre-commit" "$HOOKS_DIR/pre-push"

echo "✓ 已安装 git 钩子："
echo "    .git/hooks/pre-commit   （提交前：结构 + manifest + 敏感信息 + 版本一致性 + 语法）"
echo "    .git/hooks/pre-push     （推送前：同上）"
echo ""
echo "移除：bash tools/install_git_hooks.sh --uninstall"
