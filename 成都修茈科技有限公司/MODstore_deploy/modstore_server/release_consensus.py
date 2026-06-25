"""发版闭环 ③：三端就绪对齐 + 共识聚合。

混合语义（确定性提议 + LLM 点评）：每平台发版员对目标版本做"就绪体检"——``ready``
由确定性信号判定（平台 available + 版本 diff 合法 + 无阻塞），LLM 仅生成 ``commentary``
点评，不决定共识。聚合器：``aligned`` 当且仅当所有在编平台 ready。

纯数据/逻辑，无外部依赖，便于单测。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

CONSENSUS_ALIGNED = "aligned"
CONSENSUS_BLOCKED = "blocked"
CONSENSUS_PROPOSED = "proposed"


@dataclass
class ReadinessVerdict:
    platform: str
    ready: bool
    current_name: str = ""
    target_name: str = ""
    blockers: List[str] = field(default_factory=list)
    commentary: str = ""  # LLM 点评（仅注解，不决定 ready）

    def to_dict(self) -> Dict[str, object]:
        return {
            "platform": self.platform,
            "ready": self.ready,
            "current_name": self.current_name,
            "target_name": self.target_name,
            "blockers": list(self.blockers),
            "commentary": self.commentary,
        }


@dataclass
class AlignmentRecord:
    target_version: str
    in_scope: List[str]
    verdicts: Dict[str, ReadinessVerdict]
    consensus: str
    blockers: List[str] = field(default_factory=list)

    @property
    def aligned(self) -> bool:
        return self.consensus == CONSENSUS_ALIGNED

    def to_dict(self) -> Dict[str, object]:
        return {
            "target_version": self.target_version,
            "in_scope": list(self.in_scope),
            "consensus": self.consensus,
            "blockers": list(self.blockers),
            "verdicts": {k: v.to_dict() for k, v in self.verdicts.items()},
        }


def deterministic_readiness(
    platform: str,
    target_version: str,
    current_name: str,
    *,
    available: bool,
    extra_blockers: Optional[List[str]] = None,
    commentary: str = "",
) -> ReadinessVerdict:
    """确定性就绪判定：available + 目标版本非空 + 无外部阻塞即 ready。

    LLM 点评经 ``commentary`` 注入，不影响 ready 结果（混合语义）。
    """
    blockers: List[str] = list(extra_blockers or [])
    if not available:
        blockers.append("平台无原生工程/不可用")
    if not (target_version or "").strip():
        blockers.append("目标版本为空")
    ready = len(blockers) == 0
    return ReadinessVerdict(
        platform=platform,
        ready=ready,
        current_name=current_name,
        target_name=target_version,
        blockers=blockers,
        commentary=commentary,
    )


def aggregate(
    target_version: str,
    in_scope: List[str],
    verdicts: Dict[str, ReadinessVerdict],
) -> AlignmentRecord:
    """聚合三端 verdict 成共识：所有在编平台 ready 才 aligned，否则 blocked。"""
    blockers: List[str] = []
    all_ready = bool(in_scope)
    for p in in_scope:
        v = verdicts.get(p)
        if v is None:
            all_ready = False
            blockers.append(f"{p}: 无就绪反馈")
            continue
        if not v.ready:
            all_ready = False
            for b in v.blockers:
                blockers.append(f"{p}: {b}")
    consensus = CONSENSUS_ALIGNED if all_ready else CONSENSUS_BLOCKED
    return AlignmentRecord(
        target_version=target_version,
        in_scope=list(in_scope),
        verdicts=dict(verdicts),
        consensus=consensus,
        blockers=blockers,
    )
