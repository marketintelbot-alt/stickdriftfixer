#!/bin/zsh
set -euo pipefail

cd "$(dirname "$0")"
python3 -m pip install -r requirements.txt >/dev/null
exec python3 driftline_pro_gui.py
