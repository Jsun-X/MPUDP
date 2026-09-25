#!/bin/bash
set -e
USER="${1:?用法: bash tools/push_github.sh 你的GitHub用户名 [仓库名]}"
REPO="${2:-MPUDP}"
cd "$(dirname "$0")/.."
URL="https://github.com/${USER}/${REPO}.git"
if git remote get-url origin >/dev/null 2>&1; then
  git remote set-url origin "$URL"
else
  git remote add origin "$URL"
fi
echo "推送到 $URL"
echo "请先在 https://github.com/new 创建空仓库 ${REPO}（不要勾选 README）"
git push -u origin main
