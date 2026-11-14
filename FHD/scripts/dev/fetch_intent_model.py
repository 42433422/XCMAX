#!/usr/bin/env python3
"""下载语义意图识别模型（BAAI/bge-small-zh-v1.5，ONNX）到本地，供离线打包。

用法：在 FHD 目录执行 ``python scripts/dev/fetch_intent_model.py``。
生成目录 ``models/fastembed`` 会被 ``scripts/package/xcagi_backend.spec`` 打进
安装包；未生成时打包不阻断，运行时会自动回退到规则判定。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "models" / "fastembed"
MODEL = os.environ.get("XCAGI_INTENT_MODEL", "BAAI/bge-small-zh-v1.5")


def main() -> int:
    try:
        from fastembed import TextEmbedding
    except ImportError:
        print("缺少 fastembed，请先安装 requirements-server-api.txt", file=sys.stderr)
        return 1
    TARGET.mkdir(parents=True, exist_ok=True)
    embedding = TextEmbedding(model_name=MODEL, cache_dir=str(TARGET))
    # 预热一次，确保模型文件完整落盘（而不是只建索引）。
    vector = next(iter(embedding.embed(["语义意图模型预热"])))
    print(f"模型已就绪：{MODEL}，维度 {len(vector)}，目录 {TARGET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
