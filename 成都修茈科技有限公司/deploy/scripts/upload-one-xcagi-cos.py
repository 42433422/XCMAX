#!/usr/bin/env python3
"""Upload a single local file to xcagi-releases COS. Usage: upload-one-xcagi-cos.py <edition> <filename>"""
import os
import sys
from pathlib import Path

from qcloud_cos import CosConfig, CosS3Client

edition = sys.argv[1]
filename = sys.argv[2]
LOCAL = Path(f"/var/www/update/releases/stable/{edition}/{filename}")
PREFIX = os.environ.get("COS_PREFIX", "xcagi-v8.0.0").strip("/")
BUCKET = os.environ["COS_BUCKET"]
REGION = os.environ["COS_REGION"]
key = f"{PREFIX}/{edition}/{filename}"

config = CosConfig(
    Region=REGION,
    SecretId=os.environ["COS_SECRET_ID"],
    SecretKey=os.environ["COS_SECRET_KEY"],
    Scheme="https",
    Timeout=1800,
)
client = CosS3Client(config)
print(f"upload {LOCAL} -> cos://{BUCKET}/{key}", flush=True)
client.upload_file(
    Bucket=BUCKET,
    LocalFilePath=str(LOCAL),
    Key=key,
    PartSize=10,
    MAXThread=1,
    EnableMD5=True,
)
print("ok", flush=True)
