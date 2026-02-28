#!/usr/bin/env bash
# SmileLoop – Start the web application
# Usage: ./run_webapp.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Activate virtualenv if present
if [ -f .venv/bin/activate ]; then
    source .venv/bin/activate
fi

# Load .env if present
if [ -f .env ]; then
    set -a
    source .env
    set +a
    echo "  Loaded .env"
fi

# Install dependencies if needed
if ! python -c "import fastapi" 2>/dev/null; then
    echo "  Installing dependencies..."
    pip install -r requirements_webapp.txt
fi

echo ""
echo "  Starting SmileLoop..."
echo "  Open http://localhost:8000 in your browser"
echo ""

uvicorn webapp.app:app \
    --host 0.0.0.0 \
    --port 8000 \
    --reload \
    --reload-dir webapp \
    --reload-dir public
