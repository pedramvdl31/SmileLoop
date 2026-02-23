#!/usr/bin/env bash#!/usr/bin/env bash

# ------------------------------------------------# ──────────────────────────────────────────────

#  SmileLoop - Start the API server#  SmileLoop – Start the local API server

# ------------------------------------------------# ──────────────────────────────────────────────

#  Usage:  bash run_api.sh [mode] [host] [port]#  Prerequisites:

##    1. conda activate LivePortrait

#  mode:  local | modal | cloud   (default: modal)#    2. pip install -r liveportrait_api/requirements_api.txt

#  host:  bind address            (default: 127.0.0.1)#    3. Set LIVEPORTRAIT_ROOT if LivePortrait isn't at ./LivePortrait

#  port:  port number             (default: 8000)#

##  Usage:  bash run_api.sh  [host] [port]

#  Examples:#  Default:  127.0.0.1:8000

#    bash run_api.sh                     # modal on 127.0.0.1:8000# ──────────────────────────────────────────────

#    bash run_api.sh local               # local GPU inference

#    bash run_api.sh modal 0.0.0.0 8080  # modal on all interfacesset -euo pipefail

# ------------------------------------------------

HOST="${1:-127.0.0.1}"

set -euo pipefailPORT="${2:-8000}"



MODE="${1:-modal}"SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

HOST="${2:-127.0.0.1}"REPO_ROOT="$(dirname "$SCRIPT_DIR")"

PORT="${3:-8000}"

cat << 'EOF'

export INFERENCE_MODE="$MODE"

   ____            _ _      _

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"  / ___|_ __ ___  (_) | ___| |    ___   ___  _ __

REPO_ROOT="$(dirname "$SCRIPT_DIR")"  \___ \| '_ ` _ \| | |/ _ \ |   / _ \ / _ \| '_ \

   ___) | | | | | | | |  __/ |__| (_) | (_) | |_) |

cat << 'EOF'  |____/|_| |_| |_|_|_|\___|_____\___/ \___/| .__/

                                             |_|

   ____            _ _      _EOF

  / ___|_ __ ___  (_) | ___| |    ___   ___  _ __echo ""

  \___ \| '_ ` _ \| | |/ _ \ |   / _ \ / _ \| '_ \echo "  API:  http://${HOST}:${PORT}"

   ___) | | | | | | | |  __/ |__| (_) | (_) | |_) |echo "  Docs: http://${HOST}:${PORT}/docs"

  |____/|_| |_| |_|_|_|\___|_____\___/ \___/| .__/echo ""

                                             |_|

EOFcd "$REPO_ROOT"

echo ""

echo "  Mode: ${MODE}"python -m uvicorn liveportrait_api.server:app --host "$HOST" --port "$PORT" --reload

echo "  API:  http://${HOST}:${PORT}"
echo "  Docs: http://${HOST}:${PORT}/docs"
echo ""

cd "$REPO_ROOT"

python -m uvicorn liveportrait_api.server:app --host "$HOST" --port "$PORT"
