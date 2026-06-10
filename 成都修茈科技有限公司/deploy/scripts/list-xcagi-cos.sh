#!/usr/bin/env bash
set -a
source /root/.xcagi-cos.env
set +a
python3 - <<'PY'
import os
from qcloud_cos import CosConfig, CosS3Client
c = CosConfig(Region=os.environ["COS_REGION"], SecretId=os.environ["COS_SECRET_ID"], SecretKey=os.environ["COS_SECRET_KEY"], Scheme="https")
cl = CosS3Client(c)
r = cl.list_objects(Bucket=os.environ["COS_BUCKET"], Prefix=os.environ.get("COS_PREFIX", "xcagi-v8.0.0") + "/", MaxKeys=100)
for x in r.get("Contents") or []:
    print(f"{x['Key']}\t{x['Size']}")
PY
