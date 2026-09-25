#!/bin/bash
# apt 软件源不可用时，用 PyPI 安装 pip（无需 sudo）
set -e
cd "$(dirname "$0")/.."
ROOT="$(pwd)"

if [ ! -f "$ROOT/tools/get-pip.py" ]; then
  echo "下载 get-pip.py ..."
  curl -fsSL --connect-timeout 30 --max-time 300 \
    -o "$ROOT/tools/get-pip.py" \
    https://bootstrap.pypa.io/get-pip.py
fi

echo "安装 pip 到用户目录 (~/.local) ..."
python3 "$ROOT/tools/get-pip.py" --user --break-system-packages

export PATH="$HOME/.local/bin:$PATH"
echo "安装 numpy、matplotlib ..."
python3 -m pip install --user --break-system-packages numpy matplotlib

echo ""
echo "完成。请将下面一行加入 ~/.bashrc 后执行 source ~/.bashrc："
echo '  export PATH="$HOME/.local/bin:$PATH"'
echo ""
echo "然后："
echo "  cd $ROOT"
echo "  python3 -m pip install --user --break-system-packages -r requirements.txt"
echo "  python3 run_experiments.py"
