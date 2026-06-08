"""``script_agent`` 用到的核心数据结构。

聚合在一处便于跨模块复用 + 单测 mock。所有结构都是 frozen 风格的纯数据，
不绑定 ORM，方便 SSE 序列化。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class BriefInputFile:
    filename: str
    description: str = ""


@dataclass
class Brief:
    """前端"详细需求"表单的后端等价物。

    - ``goal`` / ``inputs`` / ``outputs`` / ``acceptance`` 必填（前端 lint 兜底）
    - ``fallback`` / ``references`` / ``trigger_type`` 可选
    """

    goal: str
    outputs: str
    acceptance: str
    inputs: List[BriefInputFile] = field(default_factory=list)
    fallback: str = ""
    references: Dict[str, Any] = field(default_factory=dict)
    trigger_type: str = "manual"

    def as_markdown(self) -> str:
        """渲染成 markdown 给 LLM 当 user prompt 用。"""
        lines: List[str] = []
        lines.append("# 任务目标")
        lines.append(self.goal.strip() or "(未填写)")
        lines.append("")
        lines.append("# 输入数据")
        if self.inputs:
            for f in self.inputs:
                desc = f" — {f.description}" if f.description else ""
                lines.append(f"- `{f.filename}`{desc}")
        else:
            lines.append("(无)")
        lines.append("")
        lines.append("# 输出要求")
        lines.append(self.outputs.strip() or "(未填写)")
        lines.append("")
        lines.append("# 成功判定标准")
        lines.append(self.acceptance.strip() or "(未填写)")
        if self.fallback.strip():
            lines.append("")
            lines.append("# 失败兜底")
            lines.append(self.fallback.strip())
        if self.references:
            lines.append("")
            lines.append("# 参考资料")
            for k, v in self.references.items():
                lines.append(f"- {k}: {v}")
        lines.append("")
        lines.append("# 触发方式")
        lines.append(self.trigger_type)
        return "\n".join(lines)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Brief":
        inputs_raw = data.get("inputs") or []
        inputs = [
            (
                BriefInputFile(
                    filename=str(x.get("filename") or ""),
                    description=str(x.get("description") or ""),
                )
                if isinstance(x, dict)
                else BriefInputFile(filename=str(x))
            )
            for x in inputs_raw
        ]
        return cls(
            goal=str(data.get("goal") or ""),
            outputs=str(data.get("outputs") or ""),
            acceptance=str(data.get("acceptance") or ""),
            inputs=inputs,
            fallback=str(data.get("fallback") or ""),
            references=dict(data.get("references") or {}),
            trigger_type=str(data.get("trigger_type") or "manual"),
        )


@dataclass
class ContextBundle:
    """``context_collector`` 的产物，喂给后续阶段的提示。"""

    brief_md: str
    inputs_summary: str
    kb_chunks_md: str = ""
    sdk_doc: str = ""
    allowlist_packages: List[str] = field(default_factory=list)

    def as_system_prompt_appendix(self) -> str:
        parts: List[str] = []
        if self.allowlist_packages:
            parts.append("可用第三方包（已审核 allowlist）：" + ", ".join(self.allowlist_packages))
        if self.sdk_doc:
            parts.append("modstore_runtime SDK 速查：\n" + self.sdk_doc)
        if self.kb_chunks_md:
            parts.append("相关知识片段：\n" + self.kb_chunks_md)
        return "\n\n".join(parts)


@dataclass
class PlanResult:
    """``planner`` 的产物。``plan_md`` 是给后续阶段的指令。"""

    plan_md: str
    raw: str = ""


@dataclass
class Verdict:
    """``observer`` 的最终判决。"""

    ok: bool
    reason: str = ""
    suggestions: List[str] = field(default_factory=list)


@dataclass
class AgentEvent:
    """``agent_loop`` 流式回调事件，供 SSE 直接序列化。

    ``type`` 取值：``context | plan | code | check | run | observe |
    repair | done | error``。``payload`` 内容随 type 而异。
    """

    type: str
    iteration: int
    payload: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {"type": self.type, "iteration": self.iteration, "payload": self.payload}
