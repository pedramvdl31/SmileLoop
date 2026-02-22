import os
import requests
import base64
import time

RUNPOD_API_KEY = os.environ.get("RUNPOD_API_KEY")
RUNPOD_ENDPOINT_ID = os.environ.get("RUNPOD_ENDPOINT_ID")
STORAGE_MODE = os.environ.get("STORAGE_MODE", "local")

RUNPOD_API_URL = f"https://api.runpod.ai/v2/{RUNPOD_ENDPOINT_ID}"

class RunPodError(Exception):
    pass

def run_job(image_bytes: bytes, preset: str, timeout: int = 300) -> bytes:
    """
    Submits a job to RunPod and returns the resulting MP4 bytes.
    """
    if not RUNPOD_API_KEY or not RUNPOD_ENDPOINT_ID:
        raise RunPodError("RunPod API key or endpoint ID not set in environment.")

    headers = {"Authorization": f"Bearer {RUNPOD_API_KEY}"}
    if STORAGE_MODE == "s3":
        # Placeholder: implement S3 upload and URL mode if needed
        raise NotImplementedError("S3/URL mode not implemented yet.")
    else:
        image_b64 = base64.b64encode(image_bytes).decode()
        payload = {"input": {"preset": preset, "image_base64": image_b64}}

    # Submit job
    resp = requests.post(f"{RUNPOD_API_URL}/run", json=payload, headers=headers)
    if resp.status_code != 200:
        raise RunPodError(f"RunPod job submission failed: {resp.text}")
    job_id = resp.json().get("id")
    if not job_id:
        raise RunPodError(f"No job_id returned: {resp.text}")

    # Poll for result
    poll_url = f"{RUNPOD_API_URL}/status/{job_id}"
    start = time.time()
    while time.time() - start < timeout:
        poll_resp = requests.get(poll_url, headers=headers)
        if poll_resp.status_code != 200:
            raise RunPodError(f"Polling failed: {poll_resp.text}")
        data = poll_resp.json()
        status = data.get("status")
        if status == "COMPLETED":
            output = data.get("output", {})
            if "output_url" in output:
                # Download and return mp4 bytes
                mp4_resp = requests.get(output["output_url"])
                if mp4_resp.status_code == 200:
                    return mp4_resp.content
                else:
                    raise RunPodError(f"Failed to download output mp4: {mp4_resp.text}")
            elif "output_mp4_base64" in output:
                return base64.b64decode(output["output_mp4_base64"])
            else:
                raise RunPodError(f"No output found in RunPod response: {output}")
        elif status == "FAILED":
            raise RunPodError(f"RunPod job failed: {data}")
        time.sleep(3)
    raise RunPodError("RunPod job timed out after 300s.")
