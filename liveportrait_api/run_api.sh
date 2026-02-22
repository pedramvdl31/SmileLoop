#!/usr/bin/env bash
# ──────────────────────────────────────────────
#  SmileLoop – Start the local API server
# ──────────────────────────────────────────────
#  Prerequisites:
#    1. conda activate LivePortrait
#    2. pip install -r liveportrait_api/requirements_api.txt
#    3. Set LIVEPORTRAIT_ROOT if LivePortrait isn't at ./LivePortrait
#
#  Usage:  bash run_api.sh  [host] [port]
#  Default:  127.0.0.1:8000
# ──────────────────────────────────────────────

set -euo pipefail

HOST="${1:-127.0.0.1}"
PORT="${2:-8000}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

cat << 'EOF'

   ____            _ _      _
  / ___|_ __ ___  (_) | ___| |    ___   ___  _ __
  \___ \| '_ ` _ \| | |/ _ \ |   / _ \ / _ \| '_ \
   ___) | | | | | | | |  __/ |__| (_) | (_) | |_) |
  |____/|_| |_| |_|_|_|\___|_____\___/ \___/| .__/
                                             |_|
EOF
echo ""
echo "  API:  http://${HOST}:${PORT}"
echo "  Docs: http://${HOST}:${PORT}/docs"
echo ""

cd "$REPO_ROOT"

python -m uvicorn liveportrait_api.server:app --host "$HOST" --port "$PORT" --reload
