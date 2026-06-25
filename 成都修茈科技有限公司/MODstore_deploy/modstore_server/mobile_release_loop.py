"""发版闭环编排器：discover → align → 落盘 → 审批 → 构建 → 分发 → OTA → smoke → 回滚。

状态机串联九阶段，依赖全部经 :class:`LoopDeps` 注入（GitHub/COS/服务器副作用走注入接口，
单测用 fake；生产用 :func:`default_deps` 的真实实现）。

模式：
- ``shadow``（默认）：跑到共识为止，产出 alignment 记录但**不触发任何不可逆操作**。
- ``primary``：共识 aligned 后落盘版本 → 过 redline 审批门 → 逐平台构建/分发/OTA/验证；
  smoke 失败则回滚该平台 OTA 到上一已知好版本。

iOS 默认不在 in_scope（无原生工程，走 App Store 非即时 OTA），故闭环天然只发 android+harmony。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from modstore_server import release_consensus, release_version_discovery
from modstore_server.ci_dispatch import DispatchResult
from modstore_server.release_consensus import AlignmentRecord, ReadinessVerdict
from modstore_server.release_version_discovery import ReleaseProposal

MODE_SHADOW = "shadow"
MODE_PRIMARY = "primary"


@dataclass
class LoopDeps:
    discover: Callable[[], ReleaseProposal]
    readiness: Callable[[str, ReleaseProposal], ReadinessVerdict]
    bump_version: Callable[[str], bool]
    request_approval: Callable[[AlignmentRecord], bool]
    build: Callable[[str, str], DispatchResult]
    distribute: Callable[[str, str], bool]
    ota_bump: Callable[[str, str], bool]
    smoke: Callable[[str, str], bool]
    rollback: Callable[[str, str], None]


def run_mobile_release_loop(deps: LoopDeps, *, mode: str = MODE_SHADOW) -> Dict[str, Any]:
    mode = (mode or MODE_SHADOW).strip().lower()
    if mode not in (MODE_SHADOW, MODE_PRIMARY):
        mode = MODE_SHADOW

    # ① 发现目标版本
    proposal = deps.discover()

    # ③ 三端就绪对齐 + 聚合共识
    verdicts: Dict[str, ReadinessVerdict] = {}
    for p in proposal.in_scope:
        verdicts[p] = deps.readiness(p, proposal)
    record = release_consensus.aggregate(proposal.target_version, proposal.in_scope, verdicts)

    result: Dict[str, Any] = {
        "ok": True,
        "mode": mode,
        "target_version": proposal.target_version,
        "in_scope": list(proposal.in_scope),
        "consensus": record.consensus,
        "alignment": record.to_dict(),
        "status": "",
        "per_platform": [],
    }

    if not record.aligned:
        result["status"] = "blocked"
        result["ok"] = False
        result["blockers"] = record.blockers
        return result

    if mode == MODE_SHADOW:
        result["status"] = "shadow_aligned"
        return result

    # ④ 版本落盘（真相源 + 全锚点）
    if not deps.bump_version(proposal.target_version):
        result["status"] = "bump_failed"
        result["ok"] = False
        return result

    # ⑤ redline 审批门（admin）
    approved = deps.request_approval(record)
    if not approved:
        result["status"] = "awaiting_approval"
        return result

    # ⑥–⑨ 逐平台：构建 → 分发 → OTA 抬版 → smoke（失败回滚）
    per_platform: List[Dict[str, Any]] = []
    all_ok = True
    for p in record.in_scope:
        diff = proposal.diff_for(p)
        prev = diff.current_name if diff is not None else ""
        row: Dict[str, Any] = {"platform": p, "prev_version": prev, "ok": False, "stage": ""}

        build = deps.build(p, proposal.target_version)
        row["build_run"] = build.run_id
        row["build_conclusion"] = build.conclusion
        if not build.ok:
            row["stage"] = "build"
            row["error"] = build.error
            all_ok = False
            per_platform.append(row)
            continue

        if not deps.distribute(p, proposal.target_version):
            row["stage"] = "distribute"
            all_ok = False
            per_platform.append(row)
            continue

        if not deps.ota_bump(p, proposal.target_version):
            row["stage"] = "ota"
            all_ok = False
            per_platform.append(row)
            continue

        if not deps.smoke(p, proposal.target_version):
            deps.rollback(p, prev)
            row["stage"] = "smoke"
            row["rolled_back"] = True
            all_ok = False
            per_platform.append(row)
            continue

        row["ok"] = True
        row["stage"] = "done"
        per_platform.append(row)

    result["per_platform"] = per_platform
    result["status"] = "released" if all_ok else "partial"
    result["ok"] = all_ok
    return result


# ── 生产默认依赖（真实实现；不在单测中执行）─────────────────────────────


def _derive_code(platform: str, target: str) -> int:
    parts = [int(x) for x in (target.split(".") + ["0", "0", "0"])[:3]]
    major, minor, patch = parts[0], parts[1], parts[2]
    if platform == "harmony":
        return major * 10000 + minor * 100 + patch
    if platform == "android":
        try:
            from modstore_server import download_release

            gradle = (
                download_release._repo_root()
                / "FHD"
                / "mobile-android"
                / "app"
                / "build.gradle.kts"
            )
            import re

            m = re.search(r"versionCode\s*=\s*(\d+)", gradle.read_text(encoding="utf-8"))
            if m:
                return int(m.group(1))
        except Exception:  # noqa: BLE001
            pass
        return major * 10000 + minor * 100 + patch
    return major * 10000 + minor * 100 + patch


def _default_discover() -> ReleaseProposal:
    return release_version_discovery.discover_target()


def _default_readiness(platform: str, proposal: ReleaseProposal) -> ReadinessVerdict:
    diff = proposal.diff_for(platform)
    current = diff.current_name if diff is not None else ""
    available = diff.available if diff is not None else False
    return release_consensus.deterministic_readiness(
        platform,
        proposal.target_version,
        current,
        available=available,
        commentary=f"{platform} 就绪体检：available={available}，目标 {proposal.target_version}",
    )


def _default_bump_version(target: str) -> bool:
    import subprocess

    from modstore_server import download_release

    script = download_release._repo_root() / "FHD" / "scripts" / "dev" / "version_sync.py"
    try:
        proc = subprocess.run(
            ["python3", str(script), "--set", target, "--apply"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        return proc.returncode == 0
    except Exception:  # noqa: BLE001
        return False


def _default_request_approval(record: AlignmentRecord) -> bool:
    # 默认不自动批：发版是不可逆操作，需 admin 经 redline 审批门确认。
    # 设 MOBILE_RELEASE_AUTO_APPROVE=1 仅用于受控自动化环境。
    return (os.environ.get("MOBILE_RELEASE_AUTO_APPROVE", "") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _default_build(platform: str, target: str) -> DispatchResult:
    from modstore_server import ci_dispatch

    wf = ci_dispatch.workflow_for(platform)
    if not wf:
        return DispatchResult(False, "", "", error=f"无 {platform} 发布 workflow")
    ref = os.environ.get("MOBILE_RELEASE_GIT_REF", "main")
    disp = ci_dispatch.dispatcher_for(platform)
    return disp.trigger_and_wait(wf, ref, {"version": target})


def _default_distribute(platform: str, target: str) -> bool:
    from modstore_server import download_release

    res = download_release.record_installer_push(
        release_train=f"mobile-{platform}-{target}",
        release_kind="mobile",
        cos_uploaded=False,
        actor="mobile-release-loop",
    )
    return bool(res.get("ok"))


def _default_ota_bump(platform: str, target: str) -> bool:
    from modstore_server import mobile_ota

    res = mobile_ota.set_platform_release(
        platform, latest_code=_derive_code(platform, target), latest_name=target
    )
    return bool(res.get("ok"))


def _default_smoke(platform: str, target: str) -> bool:
    base = (os.environ.get("XCAGI_PUBLIC_BASE_URL") or "https://xiu-ci.com").rstrip("/")
    try:
        import httpx

        r = httpx.get(f"{base}/app/config", params={"platform": platform}, timeout=15.0)
        if r.status_code >= 400:
            return False
        data = r.json()
        return str(data.get("latest_android_version_name") or data.get("latest_version_name") or "") == target
    except Exception:  # noqa: BLE001
        return False


def _default_rollback(platform: str, prev_version: str) -> None:
    if not prev_version:
        return
    from modstore_server import mobile_ota

    try:
        mobile_ota.set_platform_release(
            platform, latest_code=_derive_code(platform, prev_version), latest_name=prev_version
        )
    except Exception:  # noqa: BLE001
        pass


def default_deps() -> LoopDeps:
    return LoopDeps(
        discover=_default_discover,
        readiness=_default_readiness,
        bump_version=_default_bump_version,
        request_approval=_default_request_approval,
        build=_default_build,
        distribute=_default_distribute,
        ota_bump=_default_ota_bump,
        smoke=_default_smoke,
        rollback=_default_rollback,
    )


def run(*, mode: Optional[str] = None) -> Dict[str, Any]:
    """生产入口：用默认依赖跑闭环。默认 shadow，除非 MODSTORE_MOBILE_RELEASE_LOOP_MODE=primary。"""
    if mode is None:
        mode = (os.environ.get("MODSTORE_MOBILE_RELEASE_LOOP_MODE", MODE_SHADOW) or MODE_SHADOW).strip()
    return run_mobile_release_loop(default_deps(), mode=mode)


def cron_trigger_for_mobile_release_loop():
    """默认 08:35（北京时间），晚于 08:25 release_train，确保版本/产线已就绪。"""
    try:
        from zoneinfo import ZoneInfo

        from apscheduler.triggers.cron import CronTrigger

        tz = ZoneInfo(os.environ.get("MODSTORE_MOBILE_RELEASE_LOOP_TZ", "Asia/Shanghai").strip())
        hour = int(os.environ.get("MODSTORE_MOBILE_RELEASE_LOOP_HOUR", "8"))
        minute = int(os.environ.get("MODSTORE_MOBILE_RELEASE_LOOP_MINUTE", "35"))
        return CronTrigger(hour=hour, minute=minute, timezone=tz)
    except Exception:
        from apscheduler.triggers.cron import CronTrigger

        return CronTrigger(hour=8, minute=35)
