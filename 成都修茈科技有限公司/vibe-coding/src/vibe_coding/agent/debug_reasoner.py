"""Cross-frame debug reasoning: traceback × RepoIndex → hypothesis tree.

The :class:`DebugReasoner` bridges the gap between a raw exception and an
actionable :class:`ProjectPatch`. It:

1. **Parses** every frame in the traceback into ``(file, line, function)``.
2. **Enriches** each frame by querying the :class:`RepoIndex` for the symbol
   that owns that line plus a window of surrounding source.
3. **Prompts** the LLM with all enriched frames and asks for ≥2 candidate
   root-cause hypotheses, each with a concrete suggestion for which symbol to
   change and how to verify the fix.
4. **Returns** a :class:`DebugReport` that carries the hypothesis tree and
   optional suggested :class:`ProjectPatch` sketches.

The class also plugs into the existing :class:`CodeSkillRuntime` self-healing
chain as a ``CodePatchGenerator``-compatible fallback: when the rule-based and
LLM patch generators both fail, the caller can instantiate a ``DebugReasoner``
and call :meth:`generate_code_patch`, which returns a ``CodePatch`` (or
``None``) that the runtime can use directly.
"""

from __future__ import annotations

import json
import re
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..nl.llm import LLMClient
from ..nl.parsing import JSONParseError, safe_parse_json_object
from .context import AgentContext
from .repo_index import RepoIndex

# Maximum number of lines from each frame's source to include in the prompt.
_FRAME_CONTEXT_LINES = 10
# Maximum total characters for the prompt's frames section.
_MAX_PROMPT_CHARS = 12_000

_DEBUG_SYSTEM_PROMPT = textwrap.dedent(
    """\
    你是一个**多文件调试推理专家**。根据下面的异常信息和相关代码片段，给出 ≥2 个候选根因（hypothesis），
    每个候选必须包含：
    - `id`: 候选编号（h1, h2 …）
    - `hypothesis`: 用 1-2 句话描述根因
    - `evidence`: 指向哪个栈帧 / 哪一行 / 哪个符号说明了问题
    - `affected_symbols`: 需要修改的符号名列表（可空）
    - `fix_sketch`: 伪代码或简述，告诉开发者怎么改
    - `verification_plan`: 怎么验证这个修复是对的（写一条测试用例或检查方法）
    - `confidence`: high / medium / low

    只输出 JSON 对象（不要 markdown 围栏）：
    {
      "hypotheses": [...],
      "suggested_patch_briefing": "用 1-3 句话描述最有把握的那个候选的修复方向"
    }
    """
)


@dataclass(slots=True)
class FrameInfo:
    file: str
    line: int
    function: str
    source_context: str = ""
    symbols_at_line: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "file": self.file,
            "line": self.line,
            "function": self.function,
            "source_context": self.source_context,
            "symbols_at_line": self.symbols_at_line,
        }


@dataclass(slots=True)
class Hypothesis:
    id: str
    hypothesis: str
    evidence: str
    affected_symbols: list[str] = field(default_factory=list)
    fix_sketch: str = ""
    verification_plan: str = ""
    confidence: str = "medium"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "hypothesis": self.hypothesis,
            "evidence": self.evidence,
            "affected_symbols": list(self.affected_symbols),
            "fix_sketch": self.fix_sketch,
            "verification_plan": self.verification_plan,
            "confidence": self.confidence,
        }


@dataclass(slots=True)
class DebugReport:
    error_type: str
    error_message: str
    traceback_str: str
    frames: list[FrameInfo] = field(default_factory=list)
    hypotheses: list[Hypothesis] = field(default_factory=list)
    suggested_patch_briefing: str = ""
    raw_llm_response: str = ""

    def best_hypothesis(self) -> Hypothesis | None:
        if not self.hypotheses:
            return None
        order = {"high": 0, "medium": 1, "low": 2}
        return min(self.hypotheses, key=lambda h: order.get(h.confidence, 9))

    def to_dict(self) -> dict[str, Any]:
        return {
            "error_type": self.error_type,
            "error_message": self.error_message,
            "traceback_str": self.traceback_str,
            "frames": [f.to_dict() for f in self.frames],
            "hypotheses": [h.to_dict() for h in self.hypotheses],
            "suggested_patch_briefing": self.suggested_patch_briefing,
        }


class DebugReasoner:
    """Enrich tracebacks with index data and generate hypothesis trees.

    Designed to be called after both the rule-based generator and the
    standard LLM patch generator fail. The caller supplies:

    - ``llm`` — same :class:`LLMClient` as the rest of the pipeline.
    - ``index`` — the project's current :class:`RepoIndex`.
    - ``root`` — the project root so relative paths can be resolved.
    """

    def __init__(
        self,
        llm: LLMClient,
        *,
        index: RepoIndex | None = None,
        root: str | Path | None = None,
    ) -> None:
        self.llm = llm
        self.index = index
        self.root = Path(root).resolve() if root else None

    # ------------------------------------------------------------------ public

    def analyse(
        self,
        error: BaseException | None,
        *,
        traceback_str: str = "",
        context: AgentContext | None = None,
    ) -> DebugReport:
        """Full pipeline: parse frames → enrich → prompt LLM → parse hypotheses."""
        error_type = type(error).__name__ if error else "UnknownError"
        error_message = str(error) if error else ""
        tb = traceback_str or ""
        frames = self._parse_frames(tb)
        if self.index is not None and self.root is not None:
            frames = self._enrich_frames(frames)
        prompt_user = self._build_prompt(
            error_type=error_type,
            error_message=error_message,
            traceback_str=tb,
            frames=frames,
            context=context,
        )
        try:
            raw = self.llm.chat(_DEBUG_SYSTEM_PROMPT, prompt_user, json_mode=True)
        except Exception as exc:  # noqa: BLE001
            return DebugReport(
                error_type=error_type,
                error_message=error_message,
                traceback_str=tb,
                frames=frames,
                raw_llm_response=f"llm_error:{exc}",
            )
        report = DebugReport(
            error_type=error_type,
            error_message=error_message,
            traceback_str=tb,
            frames=frames,
            raw_llm_response=raw,
        )
        self._parse_llm_response(raw, report)
        return report

    def generate_code_patch(
        self,
        source_code: str,
        function_name: str,
        diagnosis: Any,
        test_cases: list[Any],
    ) -> Any | None:
        """Adapter to :class:`CodePatchGenerator` interface for the runtime chain.

        Returns a :class:`CodePatch` (or ``None``) by asking the LLM to
        produce a minimal hunk repair given the ``CodeDiagnosis``.
        """
        try:
            from ..runtime.patch_generator import CodePatch
            from ..nl.prompts import CODE_HUNK_REPAIR_PROMPT
            from ..code_factory import _apply_hunks_inline
        except ImportError:
            return None
        user_msg = (
            f"函数名: {function_name}\n\n"
            f"诊断: {diagnosis.to_dict() if hasattr(diagnosis, 'to_dict') else str(diagnosis)}\n\n"
            f"源码:\n{source_code}\n\n"
            f"测试用例: {json.dumps([tc.to_dict() if hasattr(tc, 'to_dict') else tc for tc in test_cases], ensure_ascii=False)}"
        )
        try:
            raw = self.llm.chat(CODE_HUNK_REPAIR_PROMPT, user_msg, json_mode=True)
            payload = safe_parse_json_object(raw)
        except (JSONParseError, Exception):  # noqa: BLE001
            return None
        raw_hunks = payload.get("hunks")
        if isinstance(raw_hunks, list) and raw_hunks:
            try:
                patched = _apply_hunks_inline(source_code, raw_hunks)
            except Exception:  # noqa: BLE001
                return None
        elif isinstance(payload.get("source_code"), str) and payload["source_code"].strip():
            patched = payload["source_code"].strip()
        else:
            return None
        return CodePatch(
            reason="debug_reasoner",
            original_code=source_code,
            patched_code=patched,
            diff_summary=str(payload.get("diff_summary") or "debug-reasoner repair"),
            llm_reasoning=str(payload.get("reasoning") or ""),
        )

    # ----------------------------------------------------------------- parsing

    @staticmethod
    def _parse_frames(traceback_str: str) -> list[FrameInfo]:
        frames: list[FrameInfo] = []
        pattern = re.compile(r'File "([^"]+)", line (\d+), in (\S+)')
        for m in pattern.finditer(traceback_str):
            frames.append(
                FrameInfo(
                    file=m.group(1),
                    line=int(m.group(2)),
                    function=m.group(3),
                )
            )
        return frames

    def _enrich_frames(self, frames: list[FrameInfo]) -> list[FrameInfo]:
        assert self.index is not None
        assert self.root is not None
        enriched: list[FrameInfo] = []
        for frame in frames:
            abs_path = Path(frame.file)
            try:
                rel = abs_path.resolve().relative_to(self.root).as_posix()
            except ValueError:
                rel = frame.file.replace("\\", "/")
            entry = self.index.get_file(rel)
            if entry is None:
                enriched.append(frame)
                continue
            abs_file = self.root / Path(rel)
            source_window = _read_lines(abs_file, frame.line, _FRAME_CONTEXT_LINES)
            syms = [
                s.qualified_name
                for s in entry.symbols
                if s.start_line <= frame.line <= s.end_line
            ]
            enriched.append(
                FrameInfo(
                    file=rel,
                    line=frame.line,
                    function=frame.function,
                    source_context=source_window,
                    symbols_at_line=syms,
                )
            )
        return enriched

    def _build_prompt(
        self,
        *,
        error_type: str,
        error_message: str,
        traceback_str: str,
        frames: list[FrameInfo],
        context: AgentContext | None,
    ) -> str:
        parts = [
            f"## 错误类型\n{error_type}: {error_message}",
            f"## Traceback\n```\n{traceback_str[:4_000]}\n```",
        ]
        if frames:
            frame_text = "\n".join(
                json.dumps(f.to_dict(), ensure_ascii=False) for f in frames
            )
            if len(frame_text) > _MAX_PROMPT_CHARS:
                frame_text = frame_text[:_MAX_PROMPT_CHARS] + "\n... (truncated)"
            parts.append(f"## 栈帧详情\n{frame_text}")
        if context is not None:
            block = context.to_prompt_block()
            if block:
                parts.append(block)
        return "\n\n".join(parts)

    # -------------------------------------------------------------- parse resp

    @staticmethod
    def _parse_llm_response(raw: str, report: DebugReport) -> None:
        try:
            data = safe_parse_json_object(raw)
        except JSONParseError:
            return
        for raw_h in data.get("hypotheses") or []:
            if not isinstance(raw_h, dict):
                continue
            report.hypotheses.append(
                Hypothesis(
                    id=str(raw_h.get("id") or ""),
                    hypothesis=str(raw_h.get("hypothesis") or ""),
                    evidence=str(raw_h.get("evidence") or ""),
                    affected_symbols=[str(s) for s in raw_h.get("affected_symbols") or []],
                    fix_sketch=str(raw_h.get("fix_sketch") or ""),
                    verification_plan=str(raw_h.get("verification_plan") or ""),
                    confidence=str(raw_h.get("confidence") or "medium"),
                )
            )
        report.suggested_patch_briefing = str(data.get("suggested_patch_briefing") or "")


def _read_lines(path: Path, center_line: int, radius: int) -> str:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    start = max(0, center_line - radius - 1)
    end = min(len(lines), center_line + radius)
    numbered: list[str] = []
    for idx, line in enumerate(lines[start:end], start=start + 1):
        marker = "→ " if idx == center_line else "  "
        numbered.append(f"{marker}{idx:4d}│{line}")
    return "\n".join(numbered)


__all__ = ["DebugReasoner", "DebugReport", "FrameInfo", "Hypothesis"]
