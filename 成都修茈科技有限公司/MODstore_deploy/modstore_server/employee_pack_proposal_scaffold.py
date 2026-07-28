"""Generate a safe three-file employee-pack source tree from a proposal."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict

from modstore_server.build_employee_pack import PACK_FILES_PREFIX, validate_pack_schema
from modstore_server.employee_pack_proposal import validate_proposal

_PACK_NAME_RE = re.compile(r"^[a-z0-9](?:[a-z0-9._-]{0,126}[a-z0-9])?$")
_PACK_VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")


class ProposalScaffoldError(ValueError):
    """A proposal cannot be safely materialized as an employee pack."""


def _bounded_text(value: Any, *, limit: int) -> str:
    return str(value or "").strip()[:limit]


def build_source_files(proposal: Dict[str, Any]) -> Dict[str, str]:
    """Return exactly three validated source files without touching disk."""

    validate_proposal(proposal)
    pack = proposal["employee_pack"]
    package_id = _bounded_text(pack.get("name"), limit=128)
    version = _bounded_text(proposal.get("target_version") or "1.0.0", limit=32)
    if not _PACK_NAME_RE.fullmatch(package_id):
        raise ProposalScaffoldError("unsafe package name")
    if not _PACK_VERSION_RE.fullmatch(version):
        raise ProposalScaffoldError("unsafe package version")

    skills = [_bounded_text(item, limit=96) for item in pack["skills"][:12]]
    criteria = [
        _bounded_text(item, limit=400) for item in pack["acceptance_criteria"][:12]
    ]
    prompt = _bounded_text(pack.get("prompt_template"), limit=12000)
    responsibility = _bounded_text(pack.get("responsibility"), limit=600)
    if not prompt or not criteria:
        raise ProposalScaffoldError("prompt and acceptance criteria are required")

    manifest = {
        "id": package_id,
        "name": package_id,
        "version": version,
        "source_schema_version": 1,
        "artifact": "employee_pack",
        "scope": "global",
        "department": proposal["department"],
        "description": responsibility,
        "prompt_template": prompt,
        "skills": skills,
        "tools": ["read_scorecard", "emit_markdown"],
        "employee": {
            "id": package_id,
            "label": "无人公司能力缺口分析员",
        },
        "employee_config_v2": {
            "identity": {
                "id": package_id,
                "version": version,
                "artifact": "employee_pack",
                "name": "无人公司能力缺口分析员",
                "description": responsibility,
            },
            "perception": {"type": "text"},
            "memory": {"type": "session"},
            "cognition": {
                "system_prompt": prompt,
                "reasoning_mode": "default",
            },
            "actions": {"handlers": ["llm_md", "echo"]},
        },
        "acceptance_criteria": criteria,
        "evolution_proposal": {
            "proposal_id": _bounded_text(proposal.get("proposal_id"), limit=128),
            "triggered_by": _bounded_text(proposal.get("triggered_by"), limit=64),
            "signal_score": proposal.get("signal_score"),
            "proposal_mode": _bounded_text(proposal.get("proposal_mode"), limit=64),
        },
    }
    validate_pack_schema(manifest)
    skills_manifest = {
        "skills": [
            {
                "name": skill,
                "description": f"Capability declared by autonomous proposal: {skill}",
                "inputs": ["founder_autonomy_scorecard_json"],
                "outputs": ["evidence_gap_analysis"],
            }
            for skill in skills
        ]
    }
    return {
        "manifest.json": json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        "prompt.txt": prompt + "\n",
        "skills.json": json.dumps(skills_manifest, ensure_ascii=False, indent=2) + "\n",
    }


def materialize_proposal(
    proposal: Dict[str, Any], *, repo_root: Path
) -> Dict[str, Any]:
    """Create a new source directory, refusing overwrite or path escape."""

    files = build_source_files(proposal)
    package_id = str(proposal["employee_pack"]["name"])
    version = str(proposal.get("target_version") or "1.0.0")
    source_rel = Path(PACK_FILES_PREFIX) / f"{package_id}@{version}"
    source_dir = (repo_root / source_rel).resolve()
    repo_root_resolved = repo_root.resolve()
    if repo_root_resolved not in source_dir.parents:
        raise ProposalScaffoldError("source path escapes repository")
    if source_dir.exists():
        raise ProposalScaffoldError("employee pack source already exists")
    source_dir.mkdir(parents=True)
    for filename, content in files.items():
        (source_dir / filename).write_text(content, encoding="utf-8")
    return {
        "ok": True,
        "package_id": package_id,
        "version": version,
        "source_dir": source_rel.as_posix(),
        "file_count": len(files),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--proposal-file", required=True, type=Path)
    parser.add_argument("--repo-root", required=True, type=Path)
    args = parser.parse_args()
    proposal = json.loads(args.proposal_file.read_text(encoding="utf-8"))
    print(
        json.dumps(
            materialize_proposal(proposal, repo_root=args.repo_root),
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ProposalScaffoldError",
    "build_source_files",
    "materialize_proposal",
]
