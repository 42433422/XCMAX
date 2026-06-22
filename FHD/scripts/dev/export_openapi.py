#!/usr/bin/env python3
"""从 FastAPI 应用导出 OpenAPI 3.0 spec，作为跨端契约 SSOT。

用法：
    python scripts/dev/export_openapi.py [--output contracts/openapi.json]

生成的 openapi.json 提交到仓库，各平台通过代码生成器消费：
  - frontend: openapi-typescript → src/types/api-generated.ts
  - Android: openapi-generator kotlin → com.xiuci.xcagi.mobile.api.contract
  - HarmonyOS: scripts/dev/gen_arkts_models.py → models/api-generated.ets
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

FHD_ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        default=str(FHD_ROOT / "contracts" / "openapi.json"),
        help="输出文件路径（默认: contracts/openapi.json）",
    )
    args = parser.parse_args()

    # 使用开发配置避免 SECRET_KEY 等生产环境必需变量
    os.environ.setdefault("XCAGI_SKIP_LEGACY_COMPAT_ROUTES", "1")
    os.environ.setdefault("XCAGI_DESKTOP_MODE", "1")

    # 延迟导入，确保环境变量先生效
    from app.config import DevelopmentConfig
    from app.fastapi_app.factory import create_fastapi_app

    app = create_fastapi_app(config_object=DevelopmentConfig, enable_docs=True)
    spec = app.openapi()

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # 幂等写入：仅在内容变化时更新文件
    new_content = json.dumps(spec, indent=2, ensure_ascii=False) + "\n"
    if output_path.exists():
        old_content = output_path.read_text(encoding="utf-8")
        if old_content == new_content:
            print(f"openapi.json 无变化，跳过写入: {output_path}")
            return 0

    output_path.write_text(new_content, encoding="utf-8")
    print(f"已导出 OpenAPI spec: {output_path}")
    print(f"  路径数: {len(spec.get('paths', {}))}")
    print(f"  schema 数: {len(spec.get('components', {}).get('schemas', {}))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
