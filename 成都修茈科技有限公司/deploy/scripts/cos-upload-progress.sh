#!/usr/bin/env bash
set -a
source /root/.xcagi-cos.env
set +a
python3 <<'PY'
import os
from pathlib import Path
from qcloud_cos import CosConfig, CosS3Client

for line in open("/root/.xcagi-cos.env"):
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.strip().split("=", 1)
        os.environ[k] = v

cl = CosS3Client(
    CosConfig(
        Region=os.environ["COS_REGION"],
        SecretId=os.environ["COS_SECRET_ID"],
        SecretKey=os.environ["COS_SECRET_KEY"],
        Scheme="https",
    )
)
b = os.environ["COS_BUCKET"]
files = [
    ("personal", "XCAGI-Personal-Setup-8.0.0-x64.exe"),
    ("offline", "XCAGI-Offline-Setup-8.0.0-x64.exe"),
    ("enterprise", "XCAGI-Enterprise-Setup-8.0.0-x64.exe"),
]
done_n = 0
for edition, fn in files:
    key = f"xcagi-v8.0.0/{edition}/{fn}"
    target = Path(f"/var/www/update/releases/stable/{edition}/{fn}").stat().st_size
    objs = [
        x
        for x in (cl.list_objects(Bucket=b, Prefix=key, MaxKeys=1).get("Contents") or [])
        if x["Key"] == key
    ]
    if objs and int(objs[0]["Size"]) >= target - 4096:
        print(f"{edition}: 100% 已完成")
        done_n += 1
        continue
    uid = next(
        (
            u["UploadId"]
            for u in (cl.list_multipart_uploads(Bucket=b, Prefix=key).get("Upload") or [])
            if u["Key"] == key
        ),
        None,
    )
    if uid:
        parts = cl.list_parts(Bucket=b, Key=key, UploadId=uid, MaxParts=1000).get("Part") or []
        done = sum(int(p["Size"]) for p in parts)
        pct = done * 100 / target
        print(f"{edition}: {pct:.1f}% ({done // 1024 // 1024}MB/{target // 1024 // 1024}MB)")
    else:
        print(f"{edition}: 等待中")
print(f"SUMMARY: {done_n}/3 完成")
PY
