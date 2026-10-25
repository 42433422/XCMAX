"""Generate a safe three-file employee-pack source tree from a proposal."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict

from modstore_server.build_employee_pack import PACK_FILES_PREFIX, validate_pack_schema
from modstore_server.employee_pack_proposal import validate_proposal

_PACK_NAME_RE = re.compile(r"^[a-z0-9](?:[a-z0-9._-]{0,126}[a-z0-9])?$")
_PACK_VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
_ALLOWLISTED_PACKAGE_ID = "autonomy-gap-analyst"
_SAFE_RESPONSIBILITY = (
    "Analyze founder-autonomy scorecard evidence and identify the highest-priority "
    "capability gap without fabricating completion."
)
_SAFE_PROMPT = (
    "You are the XCMAX autonomy gap analyst. Read the supplied scorecard JSON, "
    "rank only failed evidence gates, cite the exact missing receipt for each "
    "recommendation, and return one bounded next capability. Never claim customer "
    "payment, production deployment, QA, or recovery unless the evidence contains "
    "the corresponding immutable receipt."
)
_SAFE_SKILLS = [
    "scorecard-gap-analysis",
    "evidence-receipt-validation",
    "bounded-capability-planning",
]
_SAFE_CRITERIA = [
    "output names at least one failed scorecard gate when a failed gate exists",
    "every recommendation cites an evidence receipt or explicitly says missing",
    "output never converts missing customer payment evidence into a passed gate",
    "runtime contract exposes one self-contained direct_python handler",
]


class ProposalScaffoldError(ValueError):
    """A proposal cannot be safely materialized as an employee pack."""


def _bounded_text(value: Any, *, limit: int) -> str:
    return str(value or "").strip()[:limit]


def build_source_files(proposal: Dict[str, Any]) -> Dict[str, str]:
    """Compile one allowlisted pack; LLM prose never becomes executable source."""

    validate_proposal(proposal)
    if proposal.get("triggered_by") != "catalog_capability_gap":
        raise ProposalScaffoldError(
            "only allowlisted catalog gap proposals are materializable"
        )
    # This scaffold implements one reviewed capability only. The proposal's nested
    # employee-pack object can contain LLM-authored/private prose, so no value from
    # it is copied into source. Proposal generation already pins this identity; the
    # second check here makes direct callers fail closed as well.
    proposed_package_id = _bounded_text(
        proposal.get("employee_pack", {}).get("name"), limit=128
    )
    if proposed_package_id != _ALLOWLISTED_PACKAGE_ID:
        raise ProposalScaffoldError("proposal package is not allowlisted")
    package_id = _ALLOWLISTED_PACKAGE_ID
    version = _bounded_text(proposal.get("target_version") or "1.0.0", limit=32)
    if not _PACK_NAME_RE.fullmatch(package_id):
        raise ProposalScaffoldError("unsafe package name")
    if not _PACK_VERSION_RE.fullmatch(version):
        raise ProposalScaffoldError("unsafe package version")

    skills = list(_SAFE_SKILLS)
    criteria = list(_SAFE_CRITERIA)
    prompt = _SAFE_PROMPT
    responsibility = _SAFE_RESPONSIBILITY

    module_name = re.sub(r"[^a-z0-9_]+", "_", package_id.lower()).strip("_")
    runtime_module = module_name
    if runtime_module.endswith("_employee"):
        runtime_module = runtime_module[: -len("_employee")] or runtime_module

    manifest = {
        "id": package_id,
        "name": package_id,
        "version": version,
        "source_schema_version": 1,
        "artifact": "employee_pack",
        "scope": "global",
        "department": "quality",
        "industry": "AI/ERP governance",
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
            "collaboration": {"workflow": {"workflow_id": 0}},
            "actions": {
                "handlers": ["direct_python"],
                "direct_python": {
                    "module": module_name,
                    "action": "analyze",
                },
            },
            "metadata": {
                "framework_version": "2.0.0",
                "created_by": "autonomous_evolution",
            },
        },
        "acceptance_criteria": criteria,
        "evolution_proposal": {
            "proposal_sha256": hashlib.sha256(
                _bounded_text(proposal.get("proposal_id"), limit=128).encode("utf-8")
            ).hexdigest(),
            "triggered_by": "catalog_capability_gap",
            "proposal_mode": "reviewed_allowlist",
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
    employee_entry = f'''"""Self-contained scorecard gap analyst entrypoint."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict


async def run(payload: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    vendor_dir = Path(__file__).resolve().parents[1] / "vendor"
    if str(vendor_dir) not in sys.path:
        sys.path.insert(0, str(vendor_dir))
    from {runtime_module}.convert import analyze_scorecard

    result = analyze_scorecard(dict(payload or {{}}))
    return {{
        "ok": True,
        "summary": result["summary"],
        "items": result["failed_gates"],
        "warnings": result["warnings"],
        "meta": {{"handler": "direct_python", "action": "analyze"}},
    }}
'''
    analyzer = '''"""Deterministic founder-autonomy scorecard evidence analysis."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Tuple

_FAILED_STATUSES = {"fail", "failed", "missing", "blocked", "not_met", "unmet"}


def _load_scorecard(payload: Dict[str, Any]) -> Dict[str, Any]:
    raw = payload.get("scorecard", payload.get("founder_autonomy_scorecard_json", payload))
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("scorecard must be valid JSON") from exc
    if not isinstance(raw, dict):
        raise ValueError("scorecard must be a JSON object")
    return raw


def _failed(node: Dict[str, Any]) -> bool:
    status = str(node.get("status") or "").strip().lower().replace("-", "_")
    if status in _FAILED_STATUSES:
        return True
    for key in ("passed", "ok", "met"):
        if node.get(key) is False:
            return True
    return False


def _receipt(node: Dict[str, Any]) -> str:
    for key in ("missing_receipt", "required_receipt", "evidence_receipt", "receipt"):
        value = node.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:500]
    return "missing"


def _collect(value: Any, path: Tuple[str, ...], out: List[Dict[str, Any]]) -> None:
    if isinstance(value, dict):
        if _failed(value):
            name = str(
                value.get("name")
                or value.get("gate")
                or value.get("id")
                or (path[-1] if path else "gate")
            )
            receipt = _receipt(value)
            out.append(
                {
                    "gate": name[:200],
                    "path": ".".join(path)[:500],
                    "status": str(value.get("status") or "failed")[:80],
                    "missing_receipt": receipt,
                    "recommendation": (
                        f"Close gate {name[:200]} with immutable evidence: {receipt}"
                    ),
                }
            )
        for key, child in value.items():
            if isinstance(child, (dict, list)):
                _collect(child, path + (str(key),), out)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            if isinstance(child, (dict, list)):
                _collect(child, path + (str(index),), out)


def analyze_scorecard(payload: Dict[str, Any]) -> Dict[str, Any]:
    scorecard = _load_scorecard(payload)
    found: List[Dict[str, Any]] = []
    _collect(scorecard, (), found)
    unique: List[Dict[str, Any]] = []
    seen = set()
    for row in found:
        key = (row["path"], row["gate"])
        if key not in seen:
            seen.add(key)
            unique.append(row)
    warnings = [] if unique else ["No failed evidence gate was found in the supplied scorecard."]
    summary = (
        f"Found {len(unique)} failed evidence gate(s); highest priority: {unique[0]['gate']}"
        if unique
        else "No failed evidence gate found."
    )
    return {"summary": summary, "failed_gates": unique, "warnings": warnings}
'''
    return {
        "manifest.json": json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        "prompt.txt": prompt + "\n",
        "skills.json": json.dumps(skills_manifest, ensure_ascii=False, indent=2) + "\n",
        f"backend/employees/{module_name}.py": employee_entry,
        f"backend/vendor/{runtime_module}/convert.py": analyzer,
    }


def materialize_proposal(
    proposal: Dict[str, Any], *, repo_root: Path
) -> Dict[str, Any]:
    """Create a new source directory, refusing overwrite or path escape."""

    files = build_source_files(proposal)
    package_id = _ALLOWLISTED_PACKAGE_ID
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
        target = source_dir / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
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
    result = materialize_proposal(proposal, repo_root=args.repo_root)
    print(
        json.dumps(
            {
                "ok": bool(result.get("ok")),
                "file_count": int(result.get("file_count") or 0),
            },
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
