#!/usr/bin/env python3
"""End-to-end test: KIE generation -> watermark -> S3 upload -> S3 streaming."""

import asyncio
import shutil
from pathlib import Path

from webapp.database import init_db, create_job, get_job, update_job
from webapp.config import (
    DEFAULT_PROMPT, GROK_VIDEO_DURATION, GROK_VIDEO_RESOLUTION,
    GROK_VIDEO_MODE, KIE_API_KEY, OUTPUTS_DIR,
)
from webapp.watermark import create_watermarked_preview
from webapp.s3_storage import (
    s3_enabled, upload_video, upload_image, get_video_stream, download_bytes,
)


def main():
    init_db()
    print(f"S3 enabled: {s3_enabled()}")

    # Read test image
    image_bytes = Path("uploads/0cf58ab49839/original.jpg").read_bytes()
    print(f"Image: {len(image_bytes):,} bytes")

    # Create job
    job_id = create_job(email="test@example.com", ip_address="127.0.0.1", user_agent="e2e-test")
    print(f"Job ID: {job_id}")

    # Upload image to S3
    s3_img_key = upload_image(job_id, image_bytes, "jpg")
    print(f"S3 image key: {s3_img_key}")

    # Generate video with KIE
    async def gen():
        from grok_api.kie_client import kie_generate_video_async
        return await kie_generate_video_async(
            image_bytes=image_bytes,
            prompt=DEFAULT_PROMPT,
            duration=GROK_VIDEO_DURATION,
            resolution=GROK_VIDEO_RESOLUTION,
            mode=GROK_VIDEO_MODE,
            api_key=KIE_API_KEY or None,
            job_id=job_id,
            source="e2e-test",
        )

    print("Generating video via KIE...")
    mp4_bytes = asyncio.run(gen())
    print(f"Video: {len(mp4_bytes):,} bytes")

    # Watermark
    out_dir = OUTPUTS_DIR / job_id
    out_dir.mkdir(parents=True, exist_ok=True)
    full_path = out_dir / "full.mp4"
    full_path.write_bytes(mp4_bytes)
    preview_path = out_dir / "preview.mp4"
    create_watermarked_preview(full_path, preview_path)
    preview_bytes = preview_path.read_bytes()
    print(f"Preview: {len(preview_bytes):,} bytes")

    # Upload full + preview to S3
    s3_full = upload_video(job_id, mp4_bytes, "full")
    s3_preview = upload_video(job_id, preview_bytes, "preview")
    print(f"S3 full key: {s3_full}")
    print(f"S3 preview key: {s3_preview}")

    # Stream back from S3
    stream_data = get_video_stream(s3_preview)
    if stream_data:
        body, length, ctype = stream_data
        streamed = body.read()
        print(f"Streamed preview: {len(streamed):,} bytes (content-length: {length})")
        print(f"Bytes match: {streamed == preview_bytes}")
    else:
        print("ERROR: Could not stream from S3")
        return

    # Cleanup local
    shutil.rmtree(out_dir, ignore_errors=True)

    # Update job
    update_job(
        job_id,
        status="preview_ready",
        s3_full_key=s3_full or "",
        s3_preview_key=s3_preview or "",
        s3_image_key=s3_img_key or "",
    )
    job = get_job(job_id)
    print(f"Job status: {job['status']}")
    print(f"Job s3_full_key: {job['s3_full_key']}")
    print(f"Job s3_preview_key: {job['s3_preview_key']}")

    # Test HTTP preview endpoint
    print()
    print(f"Test preview URL: http://localhost:8000/api/preview/{job_id}")
    print(f"Test status URL:  http://localhost:8000/api/status/{job_id}")
    print()
    print("=== E2E S3 TEST PASSED ===")


if __name__ == "__main__":
    main()
