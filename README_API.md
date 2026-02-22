# SmileLoop API RunPod Integration

## Environment Variables

- `RUNPOD_API_KEY`: Your RunPod API key
- `RUNPOD_ENDPOINT_ID`: Your RunPod endpoint ID
- `STORAGE_MODE`: `local` (default, uses base64) or `s3` (URL mode, not implemented)
- `INFERENCE_MODE`: `local` or `cloud` (default: local)

## How to Run Locally

1. Install requirements:
   ```sh
   pip install -r requirements.txt
   ```
2. Set environment variables (example for PowerShell):
   ```powershell
   $env:RUNPOD_API_KEY = "your_key"
   $env:RUNPOD_ENDPOINT_ID = "your_endpoint_id"
   $env:INFERENCE_MODE = "cloud"  # or "local"
   ```
3. Start the server:
   ```sh
   uvicorn liveportrait_api.server:app --host 127.0.0.1 --port 8000
   ```

## How to Test with Python Requests

```python
import requests
files = {'source_image': open('your_image.jpg', 'rb')}
data = {'preset': 'gentle_smile'}
# Add ?mode=cloud or ?mode=local to test both
r = requests.post('http://127.0.0.1:8000/animate?mode=cloud', files=files, data=data)
print(r.status_code)
with open('result.mp4', 'wb') as f:
    f.write(r.content)
```

## Notes

- The `/animate` endpoint now supports both local and RunPod (cloud) inference.
- Use the `mode` query parameter or `INFERENCE_MODE` env var to select backend.
- The response includes headers `X-Inference-Mode` and `X-Inference-Time` for benchmarking.
- S3/URL mode is not implemented yet.
