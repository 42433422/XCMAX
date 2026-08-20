"""LLM 输入/输出防护（Guardrails）：prompt 注入检测 + 敏感词过滤。

- 纯规则零依赖；guardrail 自身异常一律 fail-open，绝不阻断业务。
- 评分：命中规则权重求和后封顶 1.0；≥ 阈值拦截，0.4~阈值 记录放行。
- 敏感词配置 ``config/guardrails/sensitive_words.txt`` 支持 mtime 热更新。
"""

from __future__ import annotations

import base64
import logging
import os
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

_LOG_THRESHOLD = 0.4


def _env_flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def guardrails_enabled() -> bool:
    return _env_flag("XCAGI_GUARDRAILS_ENABLED", True)


def injection_threshold() -> float:
    raw = (os.environ.get("XCAGI_GUARDRAILS_INJECTION_THRESHOLD") or "").strip()
    try:
        return max(0.0, min(1.0, float(raw)))
    except ValueError:
        return 0.7


def output_mode() -> str:
    return (os.environ.get("XCAGI_GUARDRAILS_OUTPUT_MODE") or "mask").strip().lower()


@dataclass(frozen=True)
class InjectionRule:
    rule_id: str
    category: str
    pattern: re.Pattern[str]
    weight: float


_INJ = re.IGNORECASE | re.DOTALL

INJECTION_RULES: tuple[InjectionRule, ...] = (
    InjectionRule(
        "ignore_instructions_en",
        "instruction_override",
        re.compile(r"ignore\s+(all|previous|prior|above)\s+(instructions|directives)", _INJ),
        0.7,
    ),
    InjectionRule(
        "disregard_directives_en",
        "instruction_override",
        re.compile(r"disregard\s+(all\s+)?(prior|previous)\s+(directives|instructions)", _INJ),
        0.7,
    ),
    InjectionRule(
        "ignore_instructions_zh_strict",
        "instruction_override",
        re.compile(r"忽略(以上|之前|此前|所有|全部)(的)?(指令|指示|设定|提示词)", _INJ),
        0.7,
    ),
    InjectionRule(
        "reveal_system_en",
        "prompt_extraction",
        re.compile(
            r"(reveal|show|print|repeat|output|display)\s+(me\s+)?(your|the)\s+((hidden|initial|system)\s+)?(system\s+prompt|instructions|prompt)",
            _INJ,
        ),
        0.7,
    ),
    InjectionRule(
        "reveal_system_zh",
        "prompt_extraction",
        re.compile(r"(输出|打印|告诉|展示)(我)?(你的|系统的)(系统提示|提示词|指令)", _INJ),
        0.7,
    ),
    InjectionRule(
        "role_jailbreak_en",
        "jailbreak",
        re.compile(r"you\s+are\s+now\s+(DAN|jailbreak|evil|unrestricted)", _INJ),
        0.8,
    ),
    InjectionRule(
        "no_restrictions_en",
        "jailbreak",
        re.compile(
            r"(pretend|act)\s+(you\s+have|like\s+you\s+have)\s+no\s+restrictions|override\s+(safety|restrictions|limits|guardrails)",
            _INJ,
        ),
        0.8,
    ),
    InjectionRule(
        "no_restrictions_zh",
        "jailbreak",
        re.compile(r"(没有|不受)(任何)?(限制|约束|内容审核)", _INJ),
        0.8,
    ),
    InjectionRule(
        "forget_setup_zh", "instruction_override", re.compile(r"忘记你之前的设定", _INJ), 0.7
    ),
    InjectionRule(
        "protocol_token",
        "protocol_injection",
        re.compile(
            r"<\|im_start\|>|<\|im_end\|>|<\|endoftext\|>|\[INST\]|\[/INST\]|<<SYS>>|<</SYS>>", _INJ
        ),
        0.9,
    ),
    InjectionRule("fence_system", "protocol_injection", re.compile(r"```\s*system", _INJ), 0.5),
)

_BASE64_TOKEN = re.compile(r"[A-Za-z0-9+/]{120,}={0,2}")


@dataclass
class GuardrailResult:
    score: float = 0.0
    action: str = "allow"  # allow | log | block
    hits: list[dict[str, Any]] = field(default_factory=list)


def _score_to_action(score: float) -> str:
    if score >= injection_threshold():
        return "block"
    if score >= _LOG_THRESHOLD:
        return "log"
    return "allow"


def _detect_injection(text: str) -> GuardrailResult:
    hits: list[dict[str, Any]] = []
    score = 0.0
    for rule in INJECTION_RULES:
        match = rule.pattern.search(text)
        if match:
            hits.append(
                {
                    "rule_id": rule.rule_id,
                    "category": rule.category,
                    "weight": rule.weight,
                    "excerpt": match.group(0)[:80],
                }
            )
            score += rule.weight
    for token in _BASE64_TOKEN.findall(text):
        try:
            decoded = base64.b64decode(token + "=" * (-len(token) % 4)).decode(
                "utf-8", errors="ignore"
            )
        except RECOVERABLE_ERRORS:
            continue
        if decoded and decoded != text:
            for rule in INJECTION_RULES:
                if rule.pattern.search(decoded):
                    hits.append(
                        {
                            "rule_id": f"{rule.rule_id}@b64",
                            "category": "encoding_bypass",
                            "weight": 0.5,
                            "excerpt": token[:40],
                        }
                    )
                    score += 0.5
                    break
    score = min(1.0, score)
    return GuardrailResult(score=score, action=_score_to_action(score), hits=hits)


class SensitiveWords:
    """敏感词表：mtime 热更新。"""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._mtime: float | None = None
        self._words: list[str] = []
        self._load()

    def _load(self) -> None:
        try:
            text = self._path.read_text(encoding="utf-8")
            self._mtime = self._path.stat().st_mtime
        except (OSError, UnicodeDecodeError):
            self._words = []
            self._mtime = None
            return
        self._words = [
            line.strip()
            for line in text.splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]

    def maybe_reload(self) -> None:
        try:
            mtime = self._path.stat().st_mtime
        except OSError:
            return
        if self._mtime is None or mtime > self._mtime:
            self._load()

    def find(self, text: str) -> list[str]:
        self.maybe_reload()
        return [word for word in self._words if word in text]

    def mask(self, text: str) -> str:
        for word in self.find(text):
            text = text.replace(word, "***")
        return text


_words: SensitiveWords | None = None
_words_lock = threading.Lock()


def _words_path() -> Path:
    explicit = (os.environ.get("XCAGI_GUARDRAILS_WORDS_FILE") or "").strip()
    if explicit:
        return Path(explicit)
    from app.utils.path_io.path_utils import get_base_dir

    return Path(get_base_dir()) / "config" / "guardrails" / "sensitive_words.txt"


def get_sensitive_words() -> SensitiveWords:
    global _words
    with _words_lock:
        if _words is None:
            _words = SensitiveWords(_words_path())
        return _words


def reset_sensitive_words() -> None:
    """测试/配置变更专用。"""
    global _words
    with _words_lock:
        _words = None


def check_input(messages: list[dict[str, Any]]) -> GuardrailResult:
    """输入检查：注入检测 + 敏感词。fail-open。"""
    if not guardrails_enabled():
        return GuardrailResult()
    try:
        text = "\n".join(str(m.get("content") or "") for m in messages or [])
        result = _detect_injection(text)
        word_hits = get_sensitive_words().find(text)
        if word_hits:
            result.hits.append(
                {
                    "rule_id": "sensitive_word",
                    "category": "sensitive_word",
                    "weight": 1.0,
                    "excerpt": word_hits[0][:40],
                }
            )
            result.score = 1.0
            result.action = "block"
        return result
    except RECOVERABLE_ERRORS:  # noqa: BLE001 — fail-open
        logger.error("guardrail check_input failed, fail-open", exc_info=True)
        return GuardrailResult()


def check_output(text: str) -> tuple[str, GuardrailResult]:
    """输出检查：敏感词 mask / strict 拦截。fail-open，返回 (处理后文本, 结果)。"""
    if not guardrails_enabled():
        return text, GuardrailResult()
    try:
        hits = get_sensitive_words().find(text)
        if not hits:
            return text, GuardrailResult()
        result = GuardrailResult(
            score=1.0,
            action="block" if output_mode() == "strict" else "log",
            hits=[
                {
                    "rule_id": "sensitive_word_output",
                    "category": "sensitive_word",
                    "weight": 1.0,
                    "excerpt": hits[0][:40],
                }
            ],
        )
        if result.action == "block":
            return text, result
        return get_sensitive_words().mask(text), result
    except RECOVERABLE_ERRORS:  # noqa: BLE001 — fail-open
        logger.error("guardrail check_output failed, fail-open", exc_info=True)
        return text, GuardrailResult()
