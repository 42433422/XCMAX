"""Source-grounded automatic review of authenticated conversation captures.

Never treat an LLM confidence score, a generic tool proposal, or a shared
scope as evidence of authority. The caller has already authenticated the
memory owner and checked the write permission.
"""

from __future__ import annotations

import os
import re
from typing import Any

from app.application.persy_memory_utils import (
    _personal_subject,
    extract_explicit_memories,
)

# These candidates stay quarantined for explicit review. A scope change is
# never authorized by words embedded in the conversation.
_UNSAFE_CONTEXT = re.compile(
    r"""[\n\r"“”「」『』《》`]|(?:翻译|小说|台词|引用|示例|假设|假如|如果|例如|比如|"""
    r"""据说|听说|可能|也许|忽略|指令|权限|密码|密钥|验证码|身份证|银行卡|"""
    r"""手机号|电话|邮箱|病历|病史|诊断|政治|宗教|性取向|password|secret|token|"""
    r"""api[_ -]?key|ignore|pretend|translate|hypothetical|example|quote)""",
    re.I,
)


def review_chat_candidate(
    *,
    message: str,
    candidate: dict[str, Any],
    scope: str,
    model_verified: bool,
) -> tuple[dict[str, Any] | None, str]:
    """Approve a bounded explicit assertion only with corroborated source text.

    Explicit private remember requests also work offline. Enterprise scope
    requires model corroboration, non-personal subject and existing ACL.
    Global/cross-tenant preferences require separate confirmation.
    """
    enabled = (os.environ.get("XCAGI_MEMORY_AUTO_REVIEW") or "1").strip().lower()
    if enabled in {"0", "false", "off", "no"}:
        return None, "auto_review_disabled"
    if scope not in {"user", "tenant"}:
        return None, "scope_requires_review"
    if _UNSAFE_CONTEXT.search(message):
        return None, "sensitive_or_ambiguous_context"
    explicit = re.match(r"^请记住[：:]\s*", message)
    if not model_verified and not (explicit and scope == "user"):
        return None, "unverified_assertion_context"
    assertion = message[explicit.end():] if explicit else message
    # One unambiguous assertion only: avoid examples and mixed-subject text.
    if re.search(r"[;；?？]", assertion):
        return None, "multiple_or_uncertain_assertions"
    rows = extract_explicit_memories(assertion)
    if len(rows) != 1:
        return None, "source_not_corroborated"
    canonical = rows[0]
    value = candidate.get("value")
    source = canonical.get("value")
    if not isinstance(value, dict) or not isinstance(source, dict):
        return None, "source_not_corroborated"
    if (
        candidate.get("memory_type") != canonical.get("memory_type")
        or str(value.get("statement") or "").strip()
        != str(source.get("statement") or "").strip()
    ):
        return None, "source_not_corroborated"
    if scope == "tenant" and _personal_subject(canonical):
        return None, "private_subject_in_shared_scope"
    if not model_verified and not _personal_subject(canonical):
        return None, "offline_nonpersonal_requires_review"
    # Use the independently parsed value; never promote arbitrary model fields.
    return canonical, "explicit_source_corroborated"
