# mypy: disable-error-code="union-attr"
"""Repository-grounding utilities for daily employee briefs."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import List, Set, Tuple

from modstore_server.duty_roster import yuangon_area_for_pkg
from modstore_server.employee_runtime import load_employee_pack
from modstore_server.models import get_session_factory
from modstore_server.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def _monorepo_root_candidate(path: Path) -> Path | None:
    """从任意路径推断 monorepo 根（与 yuangon 同级）。"""
    cur = path
    for cand in (cur, *cur.parents):
        if cand.name.lower() == "modstore_deploy":
            return cand.parent
    return None


def _workspace_repo_root_candidates() -> List[Path]:
    env = (os.environ.get("MODSTORE_REPO_ROOT") or "").strip()
    if env:
        seeds = [Path(env)]
    else:
        seeds = []
        try:
            from modstore_server.integrations.ops_action_handlers import repo_root as _ops_rr

            seeds.append(Path(_ops_rr()))
        except RECOVERABLE_ERRORS:
            pass
        seeds.append(Path(__file__).resolve().parents[2])
        try:
            seeds.append(Path.cwd())
        except OSError:
            # 进程 cwd 被删除（部署换目录后未重启）时 os.getcwd() 会抛 Errno 2
            pass

    out: List[Path] = []
    seen: Set[str] = set()
    for seed in seeds:
        try:
            resolved = seed.expanduser().resolve()
        except OSError:
            continue
        key = str(resolved)
        if key not in seen:
            seen.add(key)
            out.append(resolved)
        mono = _monorepo_root_candidate(resolved)
        if mono is not None:
            mono_key = str(mono)
            if mono_key not in seen:
                seen.add(mono_key)
                out.append(mono)
    return out


def _workspace_repo_root() -> Path:
    candidates = _workspace_repo_root_candidates()
    for cand in candidates:
        if (cand / "yuangon").is_dir():
            return cand
    if candidates:
        return candidates[0]
    return Path(__file__).resolve().parents[2]


def _resolve_pack_dir(area: str, pkg_id: str) -> Tuple[Path, Path]:
    fallback_root = _workspace_repo_root()
    fallback_pack = fallback_root / "yuangon" / area / pkg_id
    for root in _workspace_repo_root_candidates():
        pack_dir = root / "yuangon" / area / pkg_id
        if pack_dir.is_dir():
            return root, pack_dir
    return fallback_root, fallback_pack


def _yuangon_grounding_enabled() -> bool:
    return (
        os.environ.get("MODSTORE_DAILY_BRIEF_GROUND_YUANGON", "1") or ""
    ).strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def _yuangon_ground_max_chars() -> int:
    """yuangon 节选总字符预算。

    历史默认 24k 在「员工大会汇报」等多文件岗位上经常触发"X 个文件因长度上限
    被截断"，让 LLM 拿到的事实根基偏少。现代 bench LLM 普遍 100k+ context，
    把默认推高到 60k、上限推到 200k，给运维一个「调大就够用」的旋钮，同时仍
    保留 2k 下限避免误配。
    """
    raw = (os.environ.get("MODSTORE_DAILY_BRIEF_GROUND_MAX_CHARS") or "").strip()
    if raw.isdigit():
        return max(2000, min(200_000, int(raw)))
    return 60_000


def _manifest_ground_globs(pkg_id: str) -> List[str]:
    """员工包 metadata ``daily_brief_ground_paths``：相对岗位目录的 glob 列表。"""
    try:
        sf = get_session_factory()
        with sf() as session:
            pack = load_employee_pack(session, pkg_id)
        man = pack.get("manifest") if isinstance(pack.get("manifest"), dict) else {}
        v2 = (
            man.get("employee_config_v2") if isinstance(man.get("employee_config_v2"), dict) else {}
        )
        meta = v2.get("metadata") if isinstance(v2.get("metadata"), dict) else {}
        raw = meta.get("daily_brief_ground_paths")
        if isinstance(raw, list):
            out: List[str] = []
            for x in raw:
                s = str(x or "").strip()
                if s and ".." not in s and not s.startswith(("/", "\\")):
                    out.append(s)
            return out
    except RECOVERABLE_ERRORS:
        logger.debug("daily brief: manifest ground globs unavailable")
    return []


def _extra_globs_from_env(pkg_id: str) -> List[str]:
    raw = (os.environ.get("MODSTORE_DAILY_BRIEF_EXTRA_GLOBS_JSON") or "").strip()
    if not raw:
        return []
    try:
        m = json.loads(raw)
        if not isinstance(m, dict):
            return []
        paths: List[str] = []
        star = m.get("*")
        if isinstance(star, list):
            paths.extend(_sanitize_glob_items(star))
        cur = m.get(pkg_id)
        if isinstance(cur, list):
            paths.extend(_sanitize_glob_items(cur))
        # 去重保序
        seen: Set[str] = set()
        out: List[str] = []
        for g in paths:
            if g not in seen:
                seen.add(g)
                out.append(g)
        return out
    except json.JSONDecodeError:
        logger.warning("MODSTORE_DAILY_BRIEF_EXTRA_GLOBS_JSON is not valid JSON")
    return []


def _sanitize_glob_items(items: List[object]) -> List[str]:
    out: List[str] = []
    for x in items:
        s = str(x or "").strip()
        if not s or ".." in s or s.startswith(("/", "\\")):
            continue
        out.append(s)
    return out


def _safe_glob_under_pack(pack_dir: Path, pattern: str) -> List[Path]:
    """仅在 ``pack_dir`` 下展开 glob，排除路径逃逸。"""
    if ".." in pattern or pattern.startswith(("/", "\\")):
        return []
    base = pack_dir.resolve()
    found: List[Path] = []
    try:
        for p in sorted(pack_dir.glob(pattern)):
            if not p.is_file():
                continue
            try:
                p.resolve().relative_to(base)
            except ValueError:
                continue
            found.append(p)
    except OSError:
        logger.warning("daily brief grounding glob failed")
    return found


def _dedupe_paths(paths: List[Path]) -> List[Path]:
    seen: Set[str] = set()
    out: List[Path] = []
    for p in paths:
        key = str(p.resolve())
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out


def _collect_pack_candidate_paths(pack_dir: Path, pkg_id: str) -> Tuple[List[Path], List[Path]]:
    """返回 (priority_paths, extended_paths)，均已去重。"""
    priority: List[Path] = []
    for rel in ("employee.yaml", "README.md", "runbook.md", "prompts/system.md"):
        p = pack_dir / rel
        if p.is_file():
            priority.append(p)
    priority.extend(sorted(pack_dir.glob("skills/*.md"))[:8])
    seen_resolved = {str(p.resolve()) for p in priority}

    extended: List[Path] = []
    for p in sorted(pack_dir.glob("prompts/*.md")):
        k = str(p.resolve())
        if k not in seen_resolved:
            extended.append(p)
            seen_resolved.add(k)
    for p in sorted(pack_dir.glob("tasks/*.json")):
        k = str(p.resolve())
        if k not in seen_resolved:
            extended.append(p)
            seen_resolved.add(k)

    for pat in _extra_globs_from_env(pkg_id):
        for p in _safe_glob_under_pack(pack_dir, pat):
            k = str(p.resolve())
            if k not in seen_resolved:
                extended.append(p)
                seen_resolved.add(k)
    for pat in _manifest_ground_globs(pkg_id):
        for p in _safe_glob_under_pack(pack_dir, pat):
            k = str(p.resolve())
            if k not in seen_resolved:
                extended.append(p)
                seen_resolved.add(k)

    return _dedupe_paths(priority), _dedupe_paths(extended)


def collect_yuangon_pack_excerpt(pkg_id: str) -> Tuple[str, List[str]]:
    """从 ``yuangon/<area>/<pkg_id>/`` 读取若干岗位文件截断拼接，供简报 LLM 锚定真实职责。"""
    warns: List[str] = []
    if not _yuangon_grounding_enabled():
        return "", warns
    area = yuangon_area_for_pkg(pkg_id)
    if not area:
        return "", warns
    root, pack_dir = _resolve_pack_dir(area, pkg_id)
    if not pack_dir.is_dir():
        warns.append(
            f"未找到本岗仓库目录 {pack_dir}（设置 MODSTORE_REPO_ROOT 或同步 yuangon/{area}/{pkg_id}）"
        )
        return "", warns
    priority_paths, extended_paths = _collect_pack_candidate_paths(pack_dir, pkg_id)
    all_paths = priority_paths + extended_paths
    if not all_paths:
        warns.append(
            f"{pack_dir} 下未发现可节选文件（employee.yaml / README / skills / prompts / tasks / globs）"
        )
        return "", warns

    budget = _yuangon_ground_max_chars()
    lines: List[str] = [
        f"## 仓库节选：yuangon/{area}/{pkg_id}",
        f"_MODSTORE_REPO_ROOT={root}_",
        "",
    ]
    header_used = sum(len(s) + 1 for s in lines)
    body_budget = max(0, budget - header_used)

    truncated_files = 0

    def _emit_block(p: Path, cap: int) -> Tuple[str, int]:
        nonlocal truncated_files
        if cap <= 0:
            return "", 0
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            warns.append(f"读取失败 {p}: {exc}")
            return "", 0
        try:
            rel_path = p.relative_to(root).as_posix()
        except ValueError:
            rel_path = str(p)
        snip = text[:cap]
        if len(text) > cap:
            truncated_files += 1
            snip += "\n…[截断]…"
        block = f"### {rel_path}\n{snip}\n\n"
        return block, len(block)

    used = 0
    # 优先路径：至少占用约 60% 预算（在扩展路径之前分配最小份额）
    np = max(1, len(priority_paths))
    ne = len(extended_paths)
    share_pri = max(400, (body_budget * 6 // 10) // np)
    for p in priority_paths:
        if used >= body_budget:
            break
        remain = body_budget - used
        cap = min(share_pri, remain)
        block, blen = _emit_block(p, cap)
        if block:
            lines.append(block)
            used += blen

    # 扩展路径：剩余预算均分
    if extended_paths and used < body_budget:
        rest = body_budget - used
        share_ext = max(300, rest // max(1, ne))
        for p in extended_paths:
            if used >= body_budget:
                break
            remain = body_budget - used
            cap = min(share_ext, remain)
            block, blen = _emit_block(p, cap)
            if block:
                lines.append(block)
                used += blen

    if truncated_files:
        logger.warning(
            "yuangon excerpt truncated %s file(s) (budget=%s)",
            truncated_files,
            budget,
        )
        warns.append(
            f"节选内 {truncated_files} 个文件因长度上限被截断（可调大 MODSTORE_DAILY_BRIEF_GROUND_MAX_CHARS）"
        )

    body = "\n".join(lines).strip()
    if len(body) > budget:
        body = body[:budget] + "\n…[总长度截断]…"
    return body, warns
