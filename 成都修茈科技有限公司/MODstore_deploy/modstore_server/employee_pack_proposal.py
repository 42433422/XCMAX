"""Lightweight, bounded employee-pack proposal generation.

This module intentionally has no database or SQLAlchemy imports so the
Evolution Orchestrator can run in a clean GitHub Actions Python environment.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)

VALID_DEPARTMENTS = {"engineering", "quality", "ops", "growth", "support", "security"}
MAX_FILES_PER_PROPOSAL = 5
MAX_TOKENS_PER_PROPOSAL = 100000
PROPOSAL_SOURCES = (
    "catalog_capability_gap",
    "legacy_usage",
    "intent_benchmark",
    "slo_metrics",
)


class ProposalValidationError(ValueError):
    """An employee-pack proposal did not pass the bounded schema."""


def _call_llm(prompt: str) -> Dict[str, Any]:
    """Call the CI platform LLM endpoint without importing database services."""

    try:
        import httpx

        api_key = str(os.environ.get("XCAGI_LLM_API_KEY") or "").strip()
        if not api_key:
            return {}
        base_url = str(
            os.environ.get("XCAGI_LLM_BASE_URL") or "https://api.deepseek.com/v1"
        ).rstrip("/")
        model = str(os.environ.get("XCAGI_LLM_MODEL") or "deepseek-chat").strip()
        explicit_endpoint = str(os.environ.get("XCAGI_LLM_ENDPOINT") or "").strip()
        normalized_key = api_key
        if normalized_key.lower().startswith("minimaxsk-cp-"):
            normalized_key = normalized_key[len("minimax") :]
        token_plan = normalized_key.lower().startswith("sk-cp-")

        if token_plan and not explicit_endpoint:
            root = base_url
            for suffix in ("/v1", "/v2", "/v3", "/v4"):
                if root.endswith(suffix):
                    root = root[: -len(suffix)].rstrip("/")
                    break
            if not root.endswith("/anthropic"):
                root = f"{root}/anthropic"
            endpoint = f"{root}/v1/messages"
            headers = {
                "x-api-key": normalized_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            }
            payload = {
                "model": model.split("/", 1)[-1],
                "max_tokens": 2000,
                "temperature": 0,
                "messages": [{"role": "user", "content": prompt}],
            }
        else:
            if explicit_endpoint:
                endpoint = explicit_endpoint
            elif base_url.endswith("/v1"):
                endpoint = f"{base_url}/chat/completions"
            else:
                endpoint = f"{base_url}/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {normalized_key}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": model,
                "temperature": 0,
                "max_tokens": 2000,
                "messages": [
                    {
                        "role": "system",
                        "content": "Return one valid JSON object and no markdown.",
                    },
                    {"role": "user", "content": prompt},
                ],
            }
        response = httpx.post(endpoint, headers=headers, json=payload, timeout=45.0)
        response.raise_for_status()
        data = response.json()
        if token_plan and not explicit_endpoint:
            blocks = data.get("content") if isinstance(data.get("content"), list) else []
            response_text = "".join(
                str(block.get("text") or "")
                for block in blocks
                if isinstance(block, dict) and block.get("type") == "text"
            )
        else:
            choices = data.get("choices") if isinstance(data.get("choices"), list) else []
            first = choices[0] if choices and isinstance(choices[0], dict) else {}
            message = first.get("message") if isinstance(first.get("message"), dict) else {}
            response_text = str(message.get("content") or "")
        match = re.search(r"\{[\s\S]*\}", response_text)
        return json.loads(match.group(0)) if match else {}
    except Exception as exc:
        logger.warning("LLM proposal call failed: %s", exc)
        return {}


def validate_proposal(proposal: Dict[str, Any]) -> None:
    """Validate a proposal before any repository files can be generated."""

    if not isinstance(proposal, dict):
        raise ProposalValidationError("proposal must be dict")
    if not str(proposal.get("proposal_id") or "").strip():
        raise ProposalValidationError("missing proposal_id")
    if proposal.get("department") not in VALID_DEPARTMENTS:
        raise ProposalValidationError(
            f"department must be one of {VALID_DEPARTMENTS}, got {proposal.get('department')}"
        )
    pack = proposal.get("employee_pack")
    if not isinstance(pack, dict):
        raise ProposalValidationError("missing employee_pack dict")
    for key in ("name", "prompt_template", "skills", "tools", "acceptance_criteria"):
        if key not in pack:
            raise ProposalValidationError(f"employee_pack missing field: {key}")
    for key in ("skills", "tools", "acceptance_criteria"):
        if not isinstance(pack.get(key), list):
            raise ProposalValidationError(f"employee_pack {key} must be list")
    if int(proposal.get("estimated_files", 999)) > MAX_FILES_PER_PROPOSAL:
        raise ProposalValidationError(
            f"estimated_files {proposal.get('estimated_files')} exceeds {MAX_FILES_PER_PROPOSAL}"
        )
    if int(proposal.get("estimated_tokens", 999999)) > MAX_TOKENS_PER_PROPOSAL:
        raise ProposalValidationError(
            "estimated_tokens "
            f"{proposal.get('estimated_tokens')} exceeds {MAX_TOKENS_PER_PROPOSAL}"
        )


def _catalog_gap_fallback(signals: Dict[str, Any]) -> Dict[str, Any]:
    """Return a deterministic safe proposal when the LLM route is unavailable."""

    gap = signals.get("catalog_capability_gap", {})
    report = gap.get("report") if isinstance(gap.get("report"), dict) else {}
    package_id = str(report.get("package_id") or "autonomy-gap-analyst").strip()
    version = str(report.get("version") or "1.0.0").strip()
    proposal_hash = hashlib.sha256(f"{package_id}@{version}".encode()).hexdigest()[:16]
    return {
        "proposal_id": f"catalog-gap-{proposal_hash}",
        "department": "quality",
        "employee_pack": {
            "name": package_id,
            "responsibility": (
                "Analyze the founder-autonomy scorecard evidence and identify the "
                "highest-priority capability gap without fabricating completion."
            ),
            "prompt_template": (
                "You are the XCMAX autonomy gap analyst. Read the supplied scorecard JSON, "
                "rank only failed evidence gates, cite the exact missing receipt for each "
                "recommendation, and return one bounded next capability. Never claim customer "
                "payment, production deployment, QA, or recovery unless the evidence contains "
                "the corresponding immutable receipt."
            ),
            "skills": [
                "scorecard-gap-analysis",
                "evidence-receipt-validation",
                "bounded-capability-planning",
            ],
            "tools": ["read_scorecard", "emit_markdown"],
            "acceptance_criteria": [
                "output names at least one failed scorecard gate when a failed gate exists",
                "every recommendation cites an evidence receipt or explicitly says missing",
                "output never converts missing customer payment evidence into a passed gate",
                "runtime contract exposes only supported llm_md and echo handlers",
            ],
        },
        "estimated_files": 3,
        "estimated_tokens": 12000,
        "target_version": version,
        "proposal_mode": "deterministic_safe_fallback",
    }


def _normalize_catalog_gap_proposal(
    proposal: Dict[str, Any], signals: Dict[str, Any]
) -> Dict[str, Any]:
    """Pin an LLM design to the exact catalog gap identity and hard limits."""

    gap = signals.get("catalog_capability_gap", {})
    report = gap.get("report") if isinstance(gap.get("report"), dict) else {}
    package_id = str(report.get("package_id") or "autonomy-gap-analyst").strip()
    version = str(report.get("version") or "1.0.0").strip()
    pack = proposal.get("employee_pack")
    if not isinstance(pack, dict):
        pack = {}
        proposal["employee_pack"] = pack
    pack["name"] = package_id
    proposal["target_version"] = version
    proposal["estimated_files"] = min(int(proposal.get("estimated_files") or 3), 3)
    proposal["estimated_tokens"] = min(
        int(proposal.get("estimated_tokens") or 12000), MAX_TOKENS_PER_PROPOSAL
    )
    return proposal


def propose_employee_pack(
    signals: Dict[str, Any],
    *,
    llm_call: Optional[Callable[[str], Dict[str, Any]]] = None,
) -> Optional[Dict[str, Any]]:
    """Generate one validated proposal from the strongest real signal."""

    if int(signals.get("signals_to_propose") or 0) == 0:
        return None
    strongest = max(
        PROPOSAL_SOURCES,
        key=lambda source: signals.get(source, {}).get("signal_score") or 0,
    )
    score = signals.get(strongest, {}).get("signal_score") or 0
    if score <= 0:
        return None

    call = llm_call or _call_llm
    raw = call(_build_proposal_prompt(strongest, signals))
    if not raw and strongest == "catalog_capability_gap":
        raw = _catalog_gap_fallback(signals)
    if not raw:
        return None
    if strongest == "catalog_capability_gap":
        raw = _normalize_catalog_gap_proposal(raw, signals)
    raw.setdefault("triggered_by", strongest)
    raw.setdefault("signal_score", score)
    validate_proposal(raw)
    return raw


def _build_proposal_prompt(source: str, signals: Dict[str, Any]) -> str:
    source_data = signals.get(source, {})
    return f"""You are designing one bounded AI employee pack for XCMAX MODstore.

Gap signal source: {source}
Signal score: {source_data.get("signal_score", 0)}
Source report: {json.dumps(source_data.get("report", {}), ensure_ascii=False)}

Output JSON only:
{{
  "proposal_id": "<stable identifier>",
  "department": "engineering|quality|ops|growth|support|security",
  "employee_pack": {{
    "name": "<safe-lowercase-pack-name>",
    "responsibility": "<one sentence>",
    "prompt_template": "<full prompt>",
    "skills": ["<skill-1>"],
    "tools": ["read_scorecard", "emit_markdown"],
    "acceptance_criteria": ["<machine-verifiable criterion>"]
  }},
  "estimated_files": <int <= 5>,
  "estimated_tokens": <int <= 100000>
}}

The generated source will be restricted to manifest.json, prompt.txt and
skills.json, reviewed through a pull request, and may use only supported
llm_md and echo runtime handlers. Never weaken governance or invent evidence.
"""


__all__ = [
    "MAX_FILES_PER_PROPOSAL",
    "MAX_TOKENS_PER_PROPOSAL",
    "PROPOSAL_SOURCES",
    "ProposalValidationError",
    "VALID_DEPARTMENTS",
    "propose_employee_pack",
    "validate_proposal",
]
