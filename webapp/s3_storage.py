# coding: utf-8
"""
SmileLoop – S3 Video Storage

Upload and retrieve videos from Amazon S3.
Uses the same AWS credentials as SES (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY).

S3 key layout:
    videos/{job_id}/full.mp4
    videos/{job_id}/preview.mp4
    uploads/{job_id}/original.{ext}
"""

import io
import traceback
from typing import Optional

from webapp.config import (
    AWS_ACCESS_KEY_ID,
    AWS_SECRET_ACCESS_KEY,
    S3_BUCKET_NAME,
    S3_REGION,
)


def _get_s3_client():
    """Create a boto3 S3 client. Returns None if not configured."""
    if not AWS_ACCESS_KEY_ID or not AWS_SECRET_ACCESS_KEY or not S3_BUCKET_NAME:
        return None
    try:
        import boto3
        return boto3.client(
            "s3",
            region_name=S3_REGION,
            aws_access_key_id=AWS_ACCESS_KEY_ID,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
        )
    except Exception as e:
        print(f"WARNING: Could not create S3 client: {e}")
        return None


def s3_enabled() -> bool:
    """Check if S3 storage is configured."""
    return bool(AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY and S3_BUCKET_NAME)


def upload_bytes(key: str, data: bytes, content_type: str = "video/mp4") -> bool:
    """
    Upload bytes to S3.

    Args:
        key: S3 object key (e.g. "videos/abc123/full.mp4")
        data: File contents as bytes
        content_type: MIME type

    Returns:
        True if uploaded successfully, False otherwise.
    """
    client = _get_s3_client()
    if not client:
        return False

    try:
        client.put_object(
            Bucket=S3_BUCKET_NAME,
            Key=key,
            Body=data,
            ContentType=content_type,
        )
        print(f"  S3: uploaded {key} ({len(data):,} bytes)")
        return True
    except Exception as e:
        print(f"ERROR: S3 upload failed for {key}: {e}")
        traceback.print_exc()
        return False


def download_bytes(key: str) -> Optional[bytes]:
    """
    Download an object from S3.

    Args:
        key: S3 object key

    Returns:
        File contents as bytes, or None on failure.
    """
    client = _get_s3_client()
    if not client:
        return None

    try:
        response = client.get_object(Bucket=S3_BUCKET_NAME, Key=key)
        data = response["Body"].read()
        return data
    except client.exceptions.NoSuchKey:
        print(f"WARNING: S3 key not found: {key}")
        return None
    except Exception as e:
        print(f"ERROR: S3 download failed for {key}: {e}")
        traceback.print_exc()
        return None


def upload_video(job_id: str, mp4_bytes: bytes, video_type: str = "full") -> Optional[str]:
    """
    Upload a video to S3.

    Args:
        job_id: The job ID
        mp4_bytes: Video file bytes
        video_type: "full" or "preview"

    Returns:
        S3 key if successful, None otherwise.
    """
    key = f"videos/{job_id}/{video_type}.mp4"
    if upload_bytes(key, mp4_bytes, content_type="video/mp4"):
        return key
    return None


def upload_image(job_id: str, image_bytes: bytes, ext: str = "jpg") -> Optional[str]:
    """
    Upload the source image to S3.

    Args:
        job_id: The job ID
        image_bytes: Image file bytes
        ext: File extension (jpg, png)

    Returns:
        S3 key if successful, None otherwise.
    """
    mime = "image/jpeg" if ext in ("jpg", "jpeg") else "image/png"
    key = f"uploads/{job_id}/original.{ext}"
    if upload_bytes(key, image_bytes, content_type=mime):
        return key
    return None


def get_video_stream(key: str) -> Optional[tuple]:
    """
    Get a streaming response body for an S3 object.
    Returns (stream, content_length, content_type) or None.
    """
    client = _get_s3_client()
    if not client:
        return None

    try:
        response = client.get_object(Bucket=S3_BUCKET_NAME, Key=key)
        return (
            response["Body"],
            response["ContentLength"],
            response.get("ContentType", "video/mp4"),
        )
    except Exception as e:
        print(f"ERROR: S3 stream failed for {key}: {e}")
        return None
