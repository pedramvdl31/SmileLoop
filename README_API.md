# SmileLoop API

## Overview

SmileLoop turns one portrait photo into a short animated MP4.
Upload a face, pick a motion preset, get a video back.

## Architecture

```
Client → FastAPI (/animate) → Inference Backend → MP4
```

Three inference backends are supported:

| Mode    | Description                        | Cost Model        |
| ------- | ---------------------------------- | ----------------- |
| `local` | Subprocess on same machine (GPU)   | Fixed server cost |
| `modal` | Modal serverless GPU (recommended) | Pay-per-request   |
| `cloud` | RunPod serverless (legacy)         | Pay-per-request   |

## Environment Variables

| Variable             | Default                  | Description                                          |
| -------------------- | ------------------------ | ---------------------------------------------------- |
| `INFERENCE_MODE`     | `local`                  | Default inference backend: `local`, `modal`, `cloud` |
| `LIVEPORTRAIT_ROOT`  | `./LivePortrait`         | Path to LivePortrait repo (local mode only)          |
| `RUNPOD_API_KEY`     | —                        | RunPod API key (cloud mode only)                     |
| `RUNPOD_ENDPOINT_ID` | —                        | RunPod endpoint ID (cloud mode only)                 |
| `MODAL_APP_NAME`     | `smileloop-liveportrait` | Modal app name                                       |

## Quick Start

### 1. Install Dependencies

```bash
pip install -r liveportrait_api/requirements_api.txt
```

### 2. Run Locally (with local GPU)

```bash
export LIVEPORTRAIT_ROOT=/path/to/LivePortrait
export INFERENCE_MODE=local
uvicorn liveportrait_api.server:app --host 0.0.0.0 --port 8000
```

### 3. Run with Modal (recommended for production)

**One-time setup:**

```bash
# Install Modal
pip install modal

# Authenticate with Modal
modal token new

# Deploy the GPU function
modal deploy liveportrait_api/modal_liveportrait.py

# Upload preset driving videos to Modal volume (first time only)
# This happens automatically on the first request for each preset
```

**Start the API server:**

```bash
export INFERENCE_MODE=modal
uvicorn liveportrait_api.server:app --host 0.0.0.0 --port 8000
```

### 4. Run with RunPod (legacy)

```bash
export RUNPOD_API_KEY=your_key
export RUNPOD_ENDPOINT_ID=your_endpoint_id
export INFERENCE_MODE=cloud
uvicorn liveportrait_api.server:app --host 0.0.0.0 --port 8000
```

## API Endpoints

### `GET /health`

Returns server status, active inference mode, and available presets.

```bash
curl http://localhost:8000/health
```

```json
{
  "status": "ok",
  "inference_mode": "modal",
  "liveportrait_found": true,
  "presets_available": ["d6_1s", "d6_5s", "d6_10s"]
}
```

### `POST /animate`

Animate a portrait photo with a motion preset.

**Parameters:**

- `source_image` (file): JPEG or PNG portrait photo (≤ 10 MB)
- `preset` (form): Motion preset name (e.g. `d6_1s`, `d6_5s`, `d6_10s`)
- `mode` (query, optional): Override inference mode (`local`, `modal`, `cloud`)

**Response:** MP4 video file

**Response Headers:**

- `X-Inference-Mode`: Which backend was used
- `X-Inference-Time`: How long inference took

**Example:**

```python
import requests, time

t = time.time()
r = requests.post(
    'http://localhost:8000/animate',
    files={'source_image': ('photo.jpg', open('photo.jpg', 'rb'), 'image/jpeg')},
    data={'preset': 'd6_1s'}
)
print(f'Time: {time.time()-t:.1f}s')
print(f'Status: {r.status_code}')

if r.status_code == 200:
    with open('result.mp4', 'wb') as f:
        f.write(r.content)
    print('Saved result.mp4')
```

**Override mode per-request:**

```python
# Force Modal
r = requests.post('http://localhost:8000/animate?mode=modal', ...)

# Force local
r = requests.post('http://localhost:8000/animate?mode=local', ...)
```

### `GET /download/{job_id}`

Download the result MP4 for a completed local job.

### `GET /job/{job_id}`

Check the status of a local job.

## GPU Server Bootstrap

For spinning up a fresh GPU instance (Lambda Cloud, etc.):

```bash
curl -sSL https://raw.githubusercontent.com/pedramvdl31/SmileLoop/main/setup_gpu_server.sh | bash
```

This automatically installs everything and starts the server.

## File Structure

```
liveportrait_api/
├── server.py                 # FastAPI app (main entry point)
├── modal_liveportrait.py     # Modal serverless GPU function
├── modal_client.py           # Client wrapper for calling Modal
├── runpod_client.py          # RunPod client (legacy)
├── requirements_api.txt      # Python dependencies
├── presets/                   # Driving motion videos (.mp4)
│   ├── d6_1s.mp4
│   ├── d6_5s.mp4
│   └── d6_10s.mp4
└── jobs/                     # Temp job storage (local mode)
```

## Cost Comparison

| Approach             | Idle Cost | Per-Request Cost | Cold Start |
| -------------------- | --------- | ---------------- | ---------- |
| Always-on GPU server | ~$0.75/hr | Included         | None       |
| Modal serverless     | $0        | ~$0.01-0.05      | ~30s first |
| RunPod serverless    | $0        | ~$0.01-0.05      | ~30s first |
