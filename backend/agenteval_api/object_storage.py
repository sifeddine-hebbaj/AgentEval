"""Large-payload offload to S3-compatible object storage (MinIO in dev).

Kept as a small, isolated module so it's trivial to point at AWS S3 in
production by only changing environment variables (endpoint_url unset).
"""
from __future__ import annotations

import os
import uuid


def _get_client():
    import boto3

    return boto3.client(
        "s3",
        endpoint_url=os.environ.get("S3_ENDPOINT_URL", "http://localhost:9000"),
        aws_access_key_id=os.environ.get("S3_ACCESS_KEY", "minioadmin"),
        aws_secret_access_key=os.environ.get("S3_SECRET_KEY", "minioadmin"),
    )


BUCKET = os.environ.get("S3_BUCKET", "agenteval-payloads")


def upload_large_payload(serialized: str) -> str:
    client = _get_client()
    try:
        client.head_bucket(Bucket=BUCKET)
    except client.exceptions.NoSuchBucket:
        client.create_bucket(Bucket=BUCKET)
    key = f"payloads/{uuid.uuid4()}.json"
    client.put_object(Bucket=BUCKET, Key=key, Body=serialized.encode("utf-8"))
    return key


def download_large_payload(key: str) -> str:
    client = _get_client()
    obj = client.get_object(Bucket=BUCKET, Key=key)
    return obj["Body"].read().decode("utf-8")
