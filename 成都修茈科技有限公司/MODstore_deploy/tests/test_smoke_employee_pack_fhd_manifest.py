"""可选：校验 MODstore 生成的 employee_pack manifest 能被 FHD 校验器接受（不启动 HTTP 服务）。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


def _fhd_root() -> Path | None:
    candidates = [
        Path(__file__).resolve().parents[2].parent / "FHD",
        Path("e:/FHD"),
        Path("E:/FHD"),
    ]
    for p in candidates:
        if (p / "app" / "infrastructure" / "mods" / "artifact_package.py").is_file():
            return p.resolve()
    return None


def test_modstore_employee_manifest_passes_fhd_validator_when_fhd_present():
    fhd = _fhd_root()
    if fhd is None:
        pytest.skip("未找到 FHD 仓库（期望 e:/FHD 或与 MODstore_deploy 同级的 FHD/）")

    root = str(fhd)
    if root not in sys.path:
        sys.path.insert(0, root)

    from modstore_server.employee_ai_scaffold import parse_employee_pack_llm_json

    raw = json.dumps(
        {
            "id": "smoke-emp-pack-ci",
            "name": "冒烟员工包",
            "version": "1.0.0",
            "description": "联调用",
            "employee": {"id": "smoke-worker", "label": "冒烟工位", "capabilities": ["echo"]},
            "xcagi_host_profile": {
                "panel_kind": "mod_http",
                "workflow_employee_row": {"panel_title": "冒烟", "workflow_placeholder": True},
            },
        },
        ensure_ascii=False,
    )
    manifest, err = parse_employee_pack_llm_json(raw)
    assert err == ""
    assert manifest is not None

    from app.infrastructure.mods.artifact_package import (  # type: ignore  # noqa: E402
        validate_employee_pack_manifest,
        validate_xcagi_host_profile_extensions,
    )

    ve = validate_employee_pack_manifest(manifest)
    assert ve == [], f"FHD validate_employee_pack_manifest: {ve}"
    ve2 = validate_xcagi_host_profile_extensions(manifest)
    assert ve2 == [], f"FHD xcagi_host_profile: {ve2}"


def test_builtin_track_id_invalid_rejected_by_fhd_when_fhd_present():
    fhd = _fhd_root()
    if fhd is None:
        pytest.skip("未找到 FHD 仓库")
    root = str(fhd)
    if root not in sys.path:
        sys.path.insert(0, root)

    from app.infrastructure.mods.artifact_package import (  # type: ignore  # noqa: E402
        validate_xcagi_host_profile_extensions,
    )

    bad = {
        "id": "x",
        "name": "n",
        "version": "1.0.0",
        "artifact": "employee_pack",
        "scope": "global",
        "employee": {"id": "e1", "label": "L"},
        "xcagi_host_profile": {
            "panel_kind": "builtin_track",
            "builtin_track_id": "not_a_real_track",
        },
    }
    errs = validate_xcagi_host_profile_extensions(bad)
    assert errs, "应拒绝未知 builtin_track_id"
