#!/usr/bin/env bash
# 一键启用 GitHub Actions CI。
#
# 背景
# ----
# 提交 .github/workflows/ 下的文件需要 push 的凭据具备 workflow scope。
# 如果你的 GitHub token 没有这个 scope，git push 会被拒：
#
#     ! [remote rejected] main -> main
#       (refusing to allow an OAuth App to create or update workflow
#        `.github/workflows/ci.yml` without `workflow` scope)
#
# 本仓库已经把 CI 配置放在 tools/github-actions/ci.yml（普通路径，可正常提交），
# 启用时只需复制到 .github/workflows/ 即可。
#
# 用法：
#     bash tools/enable_ci.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

SRC="tools/github-actions/ci.yml"
DST=".github/workflows/ci.yml"

if [ ! -f "$SRC" ]; then
    echo "✗ 找不到 $SRC" >&2
    exit 1
fi

echo "==> 检查 GitHub 凭据是否具备 workflow scope"
if ! gh auth status 2>/dev/null | grep -q "workflow"; then
    echo "  当前 token 没有 workflow scope，先尝试授权…"
    gh auth refresh -h github.com -s workflow || {
        echo ""
        echo "✗ 授权失败。可选方案："
        echo "  1) 浏览器里完成 gh auth refresh 的授权后重试本脚本"
        echo "  2) 继续用本地钩子做守卫：bash tools/install_git_hooks.sh"
        exit 1
    }
fi

mkdir -p "$(dirname "$DST")"
cp "$SRC" "$DST"

git add "$DST"
git commit -m "ci: 启用 GitHub Actions 检查

镜像一致性、Python/JS 语法、manifest 必填字段与键序的自动校验。"
git push

echo "✓ CI 已启用：$DST"
