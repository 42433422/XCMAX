"""Classify LLM-call failures so the self-evolution engine can tell an
*infrastructure* failure (LLM credit / quota exhausted) apart from a genuine
*prompt-quality* failure.

Why this exists
---------------
The employee evolution engine mutates an employee's ``system_prompt`` when that
employee "keeps failing". In production we hit a malignant idle spin: the
platform LLM quota (``llm_calls``) ran out, every employee task 403'd, the
evolution scan read those as "the prompt is bad", and burned the (already empty)
budget trying to refine prompts — which 403'd again. ~99.6% of calls failed and
useful output was ~0.

A quota/credit exhaustion is **not** a prompt problem. Mutating the prompt can
never fix it, and each refine attempt just spends budget that isn't there. The
correct response is to *circuit-break*: stop the scan and surface the real
reason, not keep churning prompts.

This module is intentionally dependency-free (stdlib only) so it can be unit
tested in isolation and imported anywhere without dragging the app/db chain in.
"""

from __future__ import annotations

from typing import Any

# Markers that identify a credit/quota/billing exhaustion rather than a bad
# response. Kept tight to avoid misclassifying ordinary failures. The canonical
# production signal is ``HTTPException(403, "配额不足: llm_calls")`` surfaced by
# ``quota_middleware.require_llm_credit``.
_QUOTA_MARKERS: tuple[str, ...] = (
    "配额不足",
    "配额已用",
    "额度不足",
    "余额不足",
    "无可用额度",
    "llm_calls",
    "insufficient_quota",
    "insufficient quota",
    "insufficient credit",
    "out of credit",
    "quota exceeded",
    "quota_exceeded",
    "exceeded your current quota",
)

# HTTP statuses that mean "payment/credit required" — never a prompt problem.
_QUOTA_STATUSES: frozenset[int] = frozenset({402, 403})


def _status_of(err: Any) -> int | None:
    """Best-effort extraction of an HTTP status from a dict result or exception."""
    if isinstance(err, dict):
        raw = err.get("status") if err.get("status") is not None else err.get("status_code")
    else:
        raw = getattr(err, "status_code", None)
    try:
        return int(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def _text_of(err: Any) -> str:
    """Best-effort flattening of an error to searchable text."""
    if err is None:
        return ""
    if isinstance(err, dict):
        return " ".join(
            str(err.get(k) or "") for k in ("error", "message", "detail", "content")
        )
    return str(err)


def is_quota_exhausted(err: Any) -> bool:
    """Return ``True`` when *err* indicates LLM credit/quota exhaustion.

    Accepts a string, an exception, or the proxy result dict
    (``{"ok": False, "status": 403, "error": "..."}``). Status 402/403 is
    treated as credit-required; otherwise the error text is matched against a
    tight marker list.
    """
    if err is None:
        return False
    if _status_of(err) in _QUOTA_STATUSES:
        return True
    text = _text_of(err)
    if not text:
        return False
    low = text.lower()
    return any(m in text or m in low for m in _QUOTA_MARKERS)


__all__ = ["is_quota_exhausted"]
