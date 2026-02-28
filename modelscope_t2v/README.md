# ModelScope Text-to-Video — Quick Test

Generate short videos from English text prompts using [ModelScope](https://huggingface.co/damo-vilab/modelscope-damo-text-to-video-synthesis) (diffusion model, ~1.7B params, Unet3D).

## Requirements

| Resource | Minimum |
|----------|---------|
| CPU RAM  | 16 GB   |
| GPU VRAM | 16 GB (NVIDIA recommended) |
| Disk     | ~10 GB for model weights |

## Setup

```bash
cd modelscope_t2v
pip install -r requirements_t2v.txt
```

## Usage

**Default prompt** ("A panda eating bamboo on a rock."):
```bash
python test_text_to_video.py
```

**Custom prompt:**
```bash
python test_text_to_video.py --prompt "A spaceship landing on Mars"
```

**All options:**
```bash
python test_text_to_video.py \
  --prompt "Ocean waves crashing at sunset" \
  --seed 42 \
  --frames 24 \
  --steps 50 \
  --output-dir ./outputs
```

| Flag | Default | Description |
|------|---------|-------------|
| `--prompt` | *A panda eating bamboo on a rock.* | English text description |
| `--seed` | `-1` (random) | Set `>=0` for reproducible results |
| `--frames` | `16` | Number of frames (affects length) |
| `--steps` | `50` | Diffusion steps (higher = better quality, slower) |
| `--model-dir` | `./weights` | Where to store/load model weights |
| `--output-dir` | `./outputs` | Where generated `.mp4` files are saved |

## What happens

1. Model weights are downloaded from HuggingFace on first run (~10 GB).
2. The diffusion pipeline initialises and generates video frames.
3. The resulting `.mp4` is saved to `outputs/`.

## Limitations

- English text only.
- Videos are short clips (a few seconds).
- Quality is research-grade, not cinema-grade.
- Cannot render clear text inside the video.
- Possible biases from training data (LAION5B, ImageNet, Webvid).
