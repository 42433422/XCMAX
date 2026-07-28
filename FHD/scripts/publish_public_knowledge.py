#!/usr/bin/env python3
"""Validate or publish the governed customer-facing Persy corpus."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from public_knowledge.publisher import (  # noqa: E402
    default_manifest_path,
    load_public_knowledge_corpus,
    publish_public_knowledge,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default=str(default_manifest_path()))
    parser.add_argument("--storage-path", default="")
    parser.add_argument("--vector-backend", default=None)
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--no-backup", action="store_true")
    args = parser.parse_args()

    if not args.publish:
        corpus = load_public_knowledge_corpus(args.manifest)
        print(
            json.dumps(
                {
                    "success": True,
                    "mode": "check",
                    "dataset_id": corpus.dataset_id,
                    "revision": corpus.revision,
                    "document_count": len(corpus.documents),
                    "quality_query_count": len(corpus.quality_queries),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    result = publish_public_knowledge(
        manifest_path=args.manifest,
        storage_path=args.storage_path or None,
        vector_backend_name=args.vector_backend,
        create_backup=not args.no_backup,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
