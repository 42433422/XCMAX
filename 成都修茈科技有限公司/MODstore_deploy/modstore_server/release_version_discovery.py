"""发版闭环 ②：确定性发现目标版本 + 每平台 current↔target diff。

目标版本来自 ``FHD/VERSION.md`` 的「XCAGI 总版本」真相源（与 ``version_sync`` 同源），
不靠 LLM 辩论。产出 :class:`ReleaseProposal` 供③就绪对齐与④版本落盘。

可注入 ``version_md_text`` / ``rel`` 以便单测；生产读真实 VERSION.md + download_release。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from modstore_server import mobile_ota

_CANONICAL_RE = re.compile(r"`([\d.]+)`")


@dataclass
class PlatformDiff:
    platform: str
    current_name: str
    target_name: str
    needs_bump: bool
    available: bool


@dataclass
class ReleaseProposal:
    target_version: str
    source: str
    platform_diffs: List[PlatformDiff] = field(default_factory=list)
    in_scope: List[str] = field(default_factory=list)

    def diff_for(self, platform: str) -> Optional[PlatformDiff]:
        for d in self.platform_diffs:
            if d.platform == platform:
                return d
        return None


def _version_md_path() -> Path:
    from modstore_server import download_release

    return download_release._repo_root() / "FHD" / "VERSION.md"


def _read_version_md() -> str:
    try:
        return _version_md_path().read_text(encoding="utf-8")
    except OSError:
        return ""


def _canonical_from_md(text: str) -> str:
    for line in text.splitlines():
        if "XCAGI 总版本" in line:
            m = _CANONICAL_RE.search(line)
            if m:
                return m.group(1)
    return ""


def discover_target(
    *,
    target_override: Optional[str] = None,
    version_md_text: Optional[str] = None,
    rel: Optional[Dict[str, Any]] = None,
) -> ReleaseProposal:
    """发现目标版本并算每平台 diff。

    target_override 优先；否则取 VERSION.md canonical。in_scope = 当前 available 的平台
    （iOS 默认不在编=无原生工程，见 mobile_ota）。
    """
    if target_override and target_override.strip():
        target = target_override.strip()
        source = "override"
    else:
        text = version_md_text if version_md_text is not None else _read_version_md()
        target = _canonical_from_md(text)
        source = "VERSION.md"

    diffs: List[PlatformDiff] = []
    in_scope: List[str] = []
    for p in mobile_ota.PLATFORMS:
        view = mobile_ota.platform_release(p, rel=rel)
        current = str(view.get("latest_name") or "")
        available = bool(view.get("available"))
        diffs.append(
            PlatformDiff(
                platform=p,
                current_name=current,
                target_name=target,
                needs_bump=bool(target) and current != target,
                available=available,
            )
        )
        if available:
            in_scope.append(p)
    return ReleaseProposal(
        target_version=target, source=source, platform_diffs=diffs, in_scope=in_scope
    )
