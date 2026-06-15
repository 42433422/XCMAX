#!/usr/bin/env python3
"""Upload /var/www/update/releases/stable to xcagi-releases COS bucket (multipart)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

try:
    from qcloud_cos import CosConfig, CosS3Client
except ImportError:
    print("pip install cos-python-sdk-v5", file=sys.stderr)
    sys.exit(1)

BUCKET = os.environ.get("COS_BUCKET", "xcagi-releases-1374207682")
REGION = os.environ.get("COS_REGION", "ap-guangzhou")
PREFIX = os.environ.get("COS_PREFIX", "xcagi-v8.0.0").strip("/")
LOCAL_ROOT = Path(os.environ.get("LOCAL_ROOT", "/var/www/update/releases/stable"))

SECRET_ID = os.environ.get("COS_SECRET_ID") or os.environ.get("TENCENT_SECRET_ID")
SECRET_KEY = os.environ.get("COS_SECRET_KEY") or os.environ.get("TENCENT_SECRET_KEY")

if not SECRET_ID or not SECRET_KEY:
    print(
        "Set COS_SECRET_ID and COS_SECRET_KEY (CAM API key with COS write on bucket).",
        file=sys.stderr,
    )
    sys.exit(1)

config = CosConfig(
    Region=REGION,
    SecretId=SECRET_ID,
    SecretKey=SECRET_KEY,
    Scheme="https",
    Timeout=1200,
)
client = CosS3Client(config)

ALLOWED = {".exe", ".dmg", ".yml", ".blockmap"}
uploaded = 0
for edition_dir in sorted(LOCAL_ROOT.iterdir()):
    if not edition_dir.is_dir():
        continue
    for f in sorted(edition_dir.iterdir()):
        if not f.is_file() or f.suffix.lower() not in ALLOWED:
            continue
        key = f"{PREFIX}/{edition_dir.name}/{f.name}"
        size_mb = f.stat().st_size / (1024 * 1024)
        print(f"upload {f} ({size_mb:.1f} MB) -> cos://{BUCKET}/{key}", flush=True)
        for attempt in range(1, 4):
            try:
                client.upload_file(
                    Bucket=BUCKET,
                    LocalFilePath=str(f),
                    Key=key,
                    PartSize=20,
                    MAXThread=3,
                    EnableMD5=True,
                )
                print(f"  ok ({attempt}/3)", flush=True)
                break
            except Exception as exc:
                print(f"  retry {attempt}/3: {exc}", flush=True)
                if attempt == 3:
                    raise
        uploaded += 1

print(f"Done. {uploaded} object(s). Verify:")
print(f"  curl -sI https://{BUCKET}.cos.{REGION}.myqcloud.com/{PREFIX}/enterprise/XCAGI-Enterprise-Setup-8.0.0-x64.exe")
