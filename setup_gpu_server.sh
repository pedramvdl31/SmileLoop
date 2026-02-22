#!/bin/bash
# ===========================================================================
# SmileLoop GPU Server Setup Script
# ===========================================================================
# Run this on a fresh Lambda Cloud (or any Ubuntu + NVIDIA GPU) instance:
#
#   curl -sSL https://raw.githubusercontent.com/pedramvdl31/SmileLoop/main/setup_gpu_server.sh | bash
#
# Or after SSH'ing in:
#   bash setup_gpu_server.sh
#
# After completion, the server will be running on port 8000.
# ===========================================================================

set -e  # Exit on any error

echo "============================================"
echo "  SmileLoop GPU Server Setup"
echo "============================================"

# --- 1. System dependencies ---
echo "[1/6] Installing system dependencies..."
sudo apt-get update -qq
sudo apt-get install -y -qq ffmpeg git python3-pip > /dev/null 2>&1
echo "  ✓ System dependencies installed"

# --- 2. Clone SmileLoop repo ---
echo "[2/6] Cloning SmileLoop repository..."
if [ -d ~/SmileLoop ]; then
    echo "  SmileLoop already exists, pulling latest..."
    cd ~/SmileLoop && git pull
else
    cd ~ && git clone https://github.com/pedramvdl31/SmileLoop.git
    cd ~/SmileLoop
fi
echo "  ✓ SmileLoop repo ready"

# --- 3. Clone LivePortrait ---
echo "[3/6] Setting up LivePortrait..."
if [ -d ~/SmileLoop/LivePortrait ]; then
    echo "  LivePortrait already exists, pulling latest..."
    cd ~/SmileLoop/LivePortrait && git pull
else
    cd ~/SmileLoop && git clone https://github.com/KlingAIResearch/LivePortrait.git
fi
echo "  ✓ LivePortrait repo ready"

# --- 4. Install Python dependencies ---
echo "[4/6] Installing Python dependencies..."
pip3 install -q fastapi uvicorn python-multipart requests 2>/dev/null
pip3 install -q -r ~/SmileLoop/LivePortrait/requirements.txt 2>/dev/null
echo "  ✓ Python dependencies installed"

# --- 5. Download pretrained weights ---
echo "[5/6] Downloading pretrained model weights..."
cd ~/SmileLoop/LivePortrait
python3 -c "
from huggingface_hub import snapshot_download
snapshot_download(
    repo_id='KwaiVGI/LivePortrait',
    local_dir='pretrained_weights/liveportrait'
)
" 2>/dev/null

# Fix nested directory structure
cd pretrained_weights/liveportrait
if [ -d "liveportrait/base_models" ]; then
    cp -r liveportrait/base_models . 2>/dev/null
    cp -r liveportrait/retargeting_models . 2>/dev/null
    cp liveportrait/landmark.onnx . 2>/dev/null
    echo "  ✓ Model weights downloaded and arranged"
else
    echo "  ✓ Model weights already in correct location"
fi

# --- 6. Start the server ---
echo "[6/6] Starting SmileLoop API server..."
pkill -9 -f uvicorn 2>/dev/null || true
sleep 1
cd ~/SmileLoop
export LIVEPORTRAIT_ROOT=~/SmileLoop/LivePortrait
nohup python3 -m uvicorn liveportrait_api.server:app --host 0.0.0.0 --port 8000 > ~/SmileLoop/server.log 2>&1 &
sleep 3

# --- Verify ---
echo ""
echo "============================================"
echo "  Setup Complete!"
echo "============================================"
echo ""
echo "  Server log:"
cat ~/SmileLoop/server.log
echo ""
echo "  Health check:"
curl -s http://localhost:8000/health | python3 -m json.tool
echo ""
echo "============================================"
echo "  SmileLoop API is running on port 8000"
echo "  Test from your local machine:"
echo "  curl http://$(hostname -I | awk '{print $1}'):8000/health"
echo "============================================"
