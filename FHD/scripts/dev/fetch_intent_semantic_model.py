"""下载意图语义兜底模型到指定目录，供桌面端离线打包。

用法：
    python scripts/dev/fetch_intent_semantic_model.py
    python scripts/dev/fetch_intent_semantic_model.py --output assets/models/fastembed
"""

from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / "assets" / "models" / "fastembed"
DEFAULT_MODEL = "BAAI/bge-small-zh-v1.5"


def main() -> int:
    parser = argparse.ArgumentParser(description="fetch intent semantic embedding model")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()

    try:
        from fastembed import TextEmbedding
    except ImportError:
        print("fastembed 未安装：先运行 uv sync --extra intent-semantic")
        return 2

    output = Path(args.output).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)

    model = TextEmbedding(model_name=args.model, cache_dir=str(output))
    list(model.embed(["预热"]))
    size_mb = sum(p.stat().st_size for p in output.rglob("*") if p.is_file()) / (1024 * 1024)
    print(f"model={args.model} output={output} size={size_mb:.1f}MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
