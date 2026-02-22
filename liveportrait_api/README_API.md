# SmileLoop API – Phase 1 (Local Development)

> Upload a portrait → pick a motion → get an animated MP4.  
> Powered by [LivePortrait](https://github.com/KlingAIResearch/LivePortrait) under the hood.

---

## How it works

```
┌─────────────┐   POST /animate   ┌──────────────────┐   subprocess   ┌──────────────┐
│  Client /    │ ─────────────────►│  SmileLoop API   │──────────────►│  LivePortrait │
│  Frontend    │   source_image    │  (FastAPI)        │  inference.py │  (untouched)  │
│              │   + preset        │                   │               │               │
│              │ ◄─────────────────│  { job_id, url }  │◄──────────────│  output .mp4  │
└─────────────┘   GET /download/…  └──────────────────┘               └──────────────┘
```

| Route                | Method | Purpose                                                      |
| -------------------- | ------ | ------------------------------------------------------------ |
| `/animate`           | POST   | Submit a portrait + preset → returns `job_id` + download URL |
| `/download/{job_id}` | GET    | Download the generated MP4                                   |
| `/job/{job_id}`      | GET    | Check job status                                             |
| `/health`            | GET    | Health check + diagnostics                                   |
| `/docs`              | GET    | Interactive Swagger UI (auto-generated)                      |

---

## Presets

| Preset name    | File                       | Description           |
| -------------- | -------------------------- | --------------------- |
| `gentle_smile` | `presets/gentle_smile.mp4` | Subtle, natural smile |
| `big_smile`    | `presets/big_smile.mp4`    | Wide, toothy grin     |
| `blink`        | `presets/blink.mp4`        | Natural blink         |

You provide these driving-motion clips. Short (2–5 sec, 25 fps), frontal face, neutral first frame.

---

## Directory structure

```
SmileLoop/                             ← this repo
├── liveportrait_api/
│   ├── server.py                      ← FastAPI application
│   ├── __init__.py
│   ├── requirements_api.txt
│   ├── run_api.bat                    ← Windows launcher
│   ├── run_api.sh                     ← Linux / macOS launcher
│   ├── README_API.md                  ← you are here
│   ├── .gitignore
│   ├── presets/
│   │   ├── gentle_smile.mp4           ← you provide these
│   │   ├── big_smile.mp4
│   │   └── blink.mp4
│   └── jobs/                          ← auto-created, auto-cleaned (1 hr TTL)
│
└── LivePortrait/                      ← clone of KlingAIResearch/LivePortrait
    ├── inference.py                     (or set LIVEPORTRAIT_ROOT env var)
    ├── src/
    └── pretrained_weights/
```

> **The LivePortrait repo is NOT modified.** SmileLoop only adds wrapper code.

---

## Setup (one time)

### 1. Clone LivePortrait inside SmileLoop (or anywhere)

```bash
cd SmileLoop
git clone https://github.com/KlingAIResearch/LivePortrait.git
```

### 2. Set up LivePortrait's environment

```bash
conda create -n LivePortrait python=3.10
conda activate LivePortrait

cd LivePortrait
pip install -r requirements.txt

# Download pretrained weights
huggingface-cli download KlingTeam/LivePortrait --local-dir pretrained_weights \
  --exclude "*.git*" "README.md" "docs"

# Verify it works standalone
python inference.py
```

### 3. Install SmileLoop API dependencies

```bash
cd ..   # back to SmileLoop root
pip install -r liveportrait_api/requirements_api.txt
```

### 4. Add driving-motion preset videos

Place your 3 MP4 clips in `liveportrait_api/presets/`:

- `gentle_smile.mp4`
- `big_smile.mp4`
- `blink.mp4`

---

## Running the server

### Windows (PowerShell)

```powershell
conda activate LivePortrait
liveportrait_api\run_api.bat
```

### Linux / macOS

```bash
conda activate LivePortrait
bash liveportrait_api/run_api.sh
```

### Manual

```bash
python -m uvicorn liveportrait_api.server:app --host 127.0.0.1 --port 8000 --reload
```

Server runs at **http://127.0.0.1:8000**  
Swagger docs at **http://127.0.0.1:8000/docs**

### Custom LivePortrait location

If LivePortrait is not at `./LivePortrait`, set the env var:

```powershell
$env:LIVEPORTRAIT_ROOT = "C:\path\to\LivePortrait"
liveportrait_api\run_api.bat
```

---

## Usage

### Submit a job (PowerShell)

```powershell
$response = Invoke-RestMethod -Uri http://127.0.0.1:8000/animate `
  -Method Post `
  -Form @{
    source_image = Get-Item .\photo.jpg
    preset       = "gentle_smile"
  }
$response
# → { job_id: "abc123...", status: "done", download_url: "/download/abc123..." }
```

### Download result

```powershell
Invoke-WebRequest -Uri "http://127.0.0.1:8000$($response.download_url)" -OutFile result.mp4
```

### cURL (bash)

```bash
# Submit
curl -s -X POST http://127.0.0.1:8000/animate \
  -F "source_image=@photo.jpg" \
  -F "preset=gentle_smile" | jq .

# Download
curl -o result.mp4 http://127.0.0.1:8000/download/<job_id>
```

### Python

```python
import requests

# Submit
r = requests.post("http://127.0.0.1:8000/animate",
    files={"source_image": open("photo.jpg", "rb")},
    data={"preset": "big_smile"})
job = r.json()
print(job)

# Download
mp4 = requests.get(f"http://127.0.0.1:8000{job['download_url']}")
with open("result.mp4", "wb") as f:
    f.write(mp4.content)
```

---

## API reference

### `POST /animate`

| Parameter      | Type   | Location   | Description                             |
| -------------- | ------ | ---------- | --------------------------------------- |
| `source_image` | file   | multipart  | Portrait photo (JPEG or PNG, ≤ 10 MB)   |
| `preset`       | string | form field | `gentle_smile`, `big_smile`, or `blink` |

**Success (200):**

```json
{
  "job_id": "a1b2c3d4...",
  "status": "done",
  "preset": "gentle_smile",
  "download_url": "/download/a1b2c3d4..."
}
```

**Errors:**

| Code | When                            |
| ---- | ------------------------------- |
| 400  | Empty file                      |
| 413  | File > 10 MB                    |
| 415  | Not JPEG/PNG (magic byte check) |
| 422  | Invalid preset                  |
| 500  | Inference failed                |
| 503  | LivePortrait not configured     |

### `GET /download/{job_id}`

Returns the MP4 file directly (`Content-Type: video/mp4`).

### `GET /job/{job_id}`

Returns job metadata JSON (status, preset, timestamps).

### `GET /health`

```json
{
  "status": "ok",
  "liveportrait_found": true,
  "presets_available": ["gentle_smile", "big_smile", "blink"]
}
```

---

## Protections

| Protection           | How                                                    |
| -------------------- | ------------------------------------------------------ |
| **File size**        | 10 MB hard limit, checked after upload                 |
| **Image validation** | Magic-byte check (JPEG `FF D8 FF` / PNG `89 50 4E 47`) |
| **GPU concurrency**  | `asyncio.Lock` — one job at a time, others queue       |
| **Auto-cleanup**     | Background task deletes jobs older than 1 hour         |

---

## Phase 2 roadmap

- [ ] Watermarked preview (free) vs clean download (paid)
- [ ] Stripe payment integration ($3/download)
- [ ] Frontend web app
- [ ] Queue system for multiple users
- [ ] Cloud deployment (GPU instance)
