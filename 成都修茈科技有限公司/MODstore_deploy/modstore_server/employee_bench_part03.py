# ruff: noqa
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.employee_bench")


def _parse_machine_score_from_text(text: str) -> _facade().Optional[int]:
    """从质询员 Markdown 末行解析 ``MACHINE_SCORE=0..100``。"""
    if not (text or "").strip():
        return None
    lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]
    for ln in reversed(lines[-8:]):
        m = _facade().re.match("^MACHINE_SCORE\\s*=\\s*(\\d{1,3})\\s*$", ln, flags=_facade().re.I)
        if m:
            v = int(m.group(1))
            return max(0, min(100, v))
    m2 = _facade()._MACHINE_SCORE_LINE.search(text)
    if m2:
        v = int(m2.group(1))
        return max(0, min(100, v))
    return None


def _peer_review_gate_enabled() -> bool:
    return (
        _facade().os.environ.get("MODSTORE_BENCH_PEER_REVIEW_GATE", "0") or ""
    ).strip().lower() in ("1", "true", "yes", "on")


def _peer_review_min_score() -> float:
    raw = (_facade().os.environ.get("MODSTORE_BENCH_PEER_REVIEW_MIN_SCORE", "55") or "").strip()
    try:
        return float(raw)
    except ValueError:
        return 55.0


async def _run_pack_peer_review_optional(
    subject_employee_id: str,
    *,
    db: _facade().Session,
    user: _facade().User,
    bench_llm_override: _facade().Optional[_facade().Tuple[str, str]],
) -> _facade().Optional[_facade().Dict[str, _facade().Any]]:
    """若设置 ``MODSTORE_PACK_PEER_REVIEW_EMPLOYEE``，对被测包 manifest 片段跑一轮 LLM 质询并量化。

    质询员工（如 ``employee-pack-quality-interviewer``）须在输出**最后一行**写 ``MACHINE_SCORE=整数``。
    """
    reviewer = (_facade().os.environ.get("MODSTORE_PACK_PEER_REVIEW_EMPLOYEE") or "").strip()
    if not reviewer:
        return None
    if not bench_llm_override:
        return {
            "skipped": True,
            "reason": "no_platform_bench_llm",
            "reviewer_employee_id": reviewer,
            "subject_employee_id": subject_employee_id,
        }
    from modstore_server.employee_executor import execute_employee_task
    from modstore_server.mod_scaffold_runner import (
        materialize_employee_pack_if_missing,
        modstore_library_path,
    )

    materialize_employee_pack_if_missing(subject_employee_id)
    mf_path = modstore_library_path() / subject_employee_id / "manifest.json"
    if not mf_path.is_file():
        return {
            "ok": False,
            "error": "subject manifest not found",
            "reviewer_employee_id": reviewer,
            "subject_employee_id": subject_employee_id,
        }
    try:
        manifest = _facade().json.loads(mf_path.read_text(encoding="utf-8"))
    except (OSError, _facade().json.JSONDecodeError) as exc:
        return {
            "ok": False,
            "error": f"manifest read failed: {exc}",
            "reviewer_employee_id": reviewer,
            "subject_employee_id": subject_employee_id,
        }
    excerpt = _facade().json.dumps(manifest, ensure_ascii=False, indent=2)
    max_chars = int(
        (
            _facade().os.environ.get("MODSTORE_PACK_PEER_REVIEW_MAX_MANIFEST_CHARS", "14000")
            or "14000"
        ).strip()
        or "14000"
    )
    max_chars = max(2000, min(100000, max_chars))
    if len(excerpt) > max_chars:
        excerpt = excerpt[:max_chars] + "\n…[truncated for peer review]…"
    task = "对以下候选员工包（manifest JSON）执行质询面试：按你的系统提示输出 Markdown 各节；全文最后一行且仅此一行必须严格为 MACHINE_SCORE=整数（0–100），表示上架准备度量化分，该行前后不要反引号或多余文字。"
    payload: _facade().Dict[str, _facade().Any] = {
        "manifest_excerpt": excerpt,
        "target_role": str(manifest.get("name") or subject_employee_id)[:200],
        "handler": "llm_md",
    }
    import asyncio

    def _run() -> _facade().Dict[str, _facade().Any]:
        return execute_employee_task(
            reviewer, task, payload, user.id, bench_llm_override=bench_llm_override
        )

    try:
        exec_out = await asyncio.to_thread(_run)
    except Exception as exc:
        _facade().logger.warning(
            "pack peer review execute failed subject=%s reviewer=%s: %s",
            subject_employee_id,
            reviewer,
            exc,
        )
        return {
            "ok": False,
            "error": str(exc)[:500],
            "reviewer_employee_id": reviewer,
            "subject_employee_id": subject_employee_id,
        }
    text = ""
    res_block = exec_out.get("result") if isinstance(exec_out.get("result"), dict) else {}
    for block in res_block.get("outputs") or []:
        if isinstance(block, dict) and block.get("handler") == "llm_md":
            text = str(block.get("output") or "")
            break
    if not text.strip():
        text = str(exec_out.get("reasoning_excerpt") or "")[:8000]
    score = _facade()._parse_machine_score_from_text(text)
    min_sc = _facade()._peer_review_min_score()
    parsed_ok = score is not None
    pass_peer = parsed_ok and float(score) >= min_sc
    return {
        "ok": True,
        "reviewer_employee_id": reviewer,
        "subject_employee_id": subject_employee_id,
        "parsed_score": score,
        "min_score": min_sc,
        "pass_peer": pass_peer,
        "output_preview": text[:4000],
        "missing_machine_score": not parsed_ok,
    }


def _read_employee_brief(employee_id: str) -> _facade().Tuple[str, str]:
    """从本地库读取被测员工 brief + panel_summary。"""
    from modstore_server.mod_scaffold_runner import (
        materialize_employee_pack_if_missing,
        modstore_library_path,
    )

    eid = (employee_id or "").strip()
    if not eid:
        return ("", "")
    materialize_employee_pack_if_missing(eid)
    mf_path = modstore_library_path() / eid / "manifest.json"
    if not mf_path.is_file():
        return ("", "")
    try:
        mf = _facade().json.loads(mf_path.read_text(encoding="utf-8"))
    except (OSError, _facade().json.JSONDecodeError):
        return ("", "")
    brief = (
        str(mf.get("description") or "") or str((mf.get("identity") or {}).get("description") or "")
    )[:800]
    rows = mf.get("workflow_employees") or []
    panel_summary = ""
    if isinstance(rows, list) and rows and isinstance(rows[0], dict):
        panel_summary = str(rows[0].get("panel_summary") or "").strip()[:400]
    return (brief, panel_summary)


def _collect_reviewer_candidate_ids(subject_id: str) -> _facade().List[str]:
    """评审池：环境变量 CSV + 可选 catalog 全部 employee_pack（去重、排除被测 id）。"""
    import os

    subject_id = (subject_id or "").strip()
    raw = (os.environ.get("MODSTORE_BENCH_REVIEWER_POOL") or "").strip()
    ids = [x.strip() for x in raw.split(",") if x.strip()]
    flag = (os.environ.get("MODSTORE_BENCH_REVIEWER_POOL_FROM_CATALOG") or "").strip().lower()
    if flag in ("1", "true", "yes", "on"):
        try:
            from modstore_server import catalog_store

            (rows, _) = catalog_store.list_packages(
                artifact="employee_pack", q=None, limit=400, offset=0
            )
            for r in rows or []:
                pid = str(r.get("id") or "").strip()
                if pid:
                    ids.append(pid)
        except Exception as ex:
            _facade().logger.warning("reviewer pool: catalog scan failed: %s", ex)
    seen: set[str] = set()
    out: _facade().List[str] = []
    for x in ids:
        if not x or x == subject_id or x in seen:
            continue
        seen.add(x)
        out.append(x)
    return out[: _facade()._MAX_REVIEWER_CANDIDATES]


def _snapshot_reviewer_candidate(emp_id: str) -> _facade().Optional[_facade().Dict[str, str]]:
    """读取候选评审包的 id / 名称 / 简介（用于 LLM 路由）。"""
    from modstore_server.mod_scaffold_runner import (
        materialize_employee_pack_if_missing,
        modstore_library_path,
    )

    eid = (emp_id or "").strip()
    if not eid:
        return None
    materialize_employee_pack_if_missing(eid)
    mf_path = modstore_library_path() / eid / "manifest.json"
    if not mf_path.is_file():
        return None
    try:
        mf = _facade().json.loads(mf_path.read_text(encoding="utf-8"))
    except (OSError, _facade().json.JSONDecodeError):
        return None
    ident = mf.get("identity") if isinstance(mf.get("identity"), dict) else {}
    name = str(mf.get("name") or ident.get("name") or eid).strip()[:120]
    desc = str(mf.get("description") or ident.get("description") or "").strip()[:400]
    return {"id": eid, "name": name, "description": desc}


def _dimensions_still_open(
    env_defaults: _facade().Dict[str, str], explicit: _facade().Dict[str, str]
) -> _facade().List[str]:
    """尚未被环境变量或 API 显式指定的维度 → 才可自动分配。"""
    holes: _facade().List[str] = []
    for dim in _facade().AUDIT_DIMENSIONS:
        if str(explicit.get(dim) or "").strip():
            continue
        if str(env_defaults.get(dim) or "").strip():
            continue
        holes.append(dim)
    return holes


async def _llm_assign_reviewers_to_dimensions(
    subject_id: str,
    brief: str,
    panel_summary: str,
    candidates: _facade().List[_facade().Dict[str, str]],
    provider: str,
    model: str,
    holes: _facade().List[str],
) -> _facade().Tuple[_facade().Dict[str, str], _facade().Optional[str]]:
    """调用平台 LLM，为「空缺维度」从候选包中选评审参考包 id。"""
    from modstore_server.services.llm import chat_dispatch_via_platform_only

    if not holes or not candidates:
        return ({}, None)
    allowed = {c["id"] for c in candidates if c.get("id")}
    dim_lines = "\n".join(
        (f"- {d}: {_facade()._DIM_LABELS_ZH.get(d, d)}" for d in _facade().AUDIT_DIMENSIONS)
    )
    system = f"""你是员工包「五维沙盒审核」的评审路由编排器。\n沙盒会对**评审参考包本身**跑静态五维打分；合成报告时，每个维度可以引用不同参考包在该维上的得分。\n\n当前只需要为下列**尚未指定**的维度，各选一个**最合适**的候选包 id（必须从候选列表中选，禁止编造 id）。\n尚未指定维度：{', '.join(holes)}\n\n五维含义：\n{dim_lines}\n\n规则：\n1. 输出**仅**一个 JSON 对象，不要 markdown。\n2. 每个键必须是下列之一：{', '.join(_facade().AUDIT_DIMENSIONS)}\n3. **只输出你需要填写的维度**（通常是 holes 中的维度）；每个值必须是候选中的 id 字符串。\n4. 优先让五个维度覆盖不同候选（若候选不足再复用）。\n5. 结合「被测员工」的领域与候选包的名称/简介做语义匹配。\n\n示例：{{"manifest_compliance":"pkg-a","metadata_quality":"pkg-b"}}"""
    payload = {
        "subject_employee_id": subject_id,
        "subject_brief": (brief or "").strip(),
        "panel_summary": (panel_summary or "").strip(),
        "candidate_packages": candidates,
        "dimensions_to_fill": holes,
    }
    user_msg = _facade().json.dumps(payload, ensure_ascii=False)
    result = await chat_dispatch_via_platform_only(
        provider,
        model,
        [{"role": "system", "content": system}, {"role": "user", "content": user_msg}],
        max_tokens=2500,
    )
    if not result.get("ok"):
        return ({}, str(result.get("error") or "LLM router failed"))
    raw = _facade()._parse_router_json(str(result.get("content") or ""))
    out: _facade().Dict[str, str] = {}
    for dim in holes:
        v = str(raw.get(dim) or "").strip()
        if v in allowed:
            out[dim] = v
    return (out, None)


def _parse_router_json(text: str) -> _facade().Dict[str, _facade().Any]:
    raw = _facade()._strip_fence(text)
    try:
        data = _facade().json.loads(raw)
    except _facade().json.JSONDecodeError:
        (i, j) = (raw.find("{"), raw.rfind("}"))
        if i < 0 or j <= i:
            return {}
        try:
            data = _facade().json.loads(raw[i : j + 1])
        except _facade().json.JSONDecodeError:
            return {}
    return data if isinstance(data, dict) else {}


async def resolve_auto_dimension_reviewers(
    subject_id: str,
    brief: str,
    panel_summary: str,
    bench_llm_override: _facade().Optional[_facade().Tuple[str, str]],
    *,
    explicit_per_dimension: _facade().Optional[_facade().Dict[str, str]] = None,
) -> _facade().Tuple[
    _facade().Optional[_facade().Dict[str, str]], _facade().Dict[str, _facade().Any]
]:
    """从评审池 + 平台 LLM 自动为「空缺维度」挑选评审参考包。无池 / 禁用 / 无空缺时跳过。"""
    import os

    meta: _facade().Dict[str, _facade().Any] = {"enabled": False}
    if (os.environ.get("MODSTORE_BENCH_REVIEWER_DISABLE") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    ):
        meta["skipped"] = "MODSTORE_BENCH_REVIEWER_DISABLE"
        return (None, meta)
    if not bench_llm_override:
        meta["skipped"] = "no_platform_bench_llm"
        return (None, meta)
    env_defaults = _facade()._load_audit_dimension_env_defaults()
    explicit = {
        k: v
        for (k, v) in (explicit_per_dimension or {}).items()
        if k in _facade().AUDIT_DIMENSIONS and str(v or "").strip()
    }
    holes = _facade()._dimensions_still_open(env_defaults, explicit)
    if not holes:
        meta["skipped"] = "all_dimensions_preassigned"
        meta["holes"] = []
        return (None, meta)
    cand_ids = _facade()._collect_reviewer_candidate_ids(subject_id)
    if not cand_ids:
        meta["skipped"] = "empty_reviewer_pool"
        meta["hint"] = (
            "设置 MODSTORE_BENCH_REVIEWER_POOL=id1,id2 或 MODSTORE_BENCH_REVIEWER_POOL_FROM_CATALOG=1"
        )
        return (None, meta)
    candidates: _facade().List[_facade().Dict[str, str]] = []
    for cid in cand_ids:
        snap = _facade()._snapshot_reviewer_candidate(cid)
        if snap:
            candidates.append(snap)
    meta["pool_raw"] = len(cand_ids)
    meta["candidates_loaded"] = len(candidates)
    if not candidates:
        meta["skipped"] = "no_candidate_manifests"
        return (None, meta)
    (prov, mdl) = bench_llm_override
    (picked, err) = await _facade()._llm_assign_reviewers_to_dimensions(
        subject_id, brief, panel_summary, candidates, prov, mdl, holes
    )
    meta["enabled"] = True
    meta["holes"] = holes
    meta["assignment"] = picked
    if err:
        meta["error"] = err
    if not picked:
        meta["skipped"] = "llm_router_empty"
        return (None, meta)
    return (picked, meta)


def _load_audit_dimension_env_defaults() -> _facade().Dict[str, str]:
    """从服务端环境变量读取五维专属包 ID 的静态默认映射。

    环境变量命名规则：``MODSTORE_AUDIT_DIM_<DIMENSION_UPPER>_EMPLOYEE``。
    例：``MODSTORE_AUDIT_DIM_MANIFEST_COMPLIANCE_EMPLOYEE=python-docstring-gen``
    """
    import os

    result: _facade().Dict[str, str] = {}
    for dim in _facade().AUDIT_DIMENSIONS:
        env_key = f"MODSTORE_AUDIT_DIM_{dim.upper()}_EMPLOYEE"
        val = (os.environ.get(env_key) or "").strip()
        if val:
            result[dim] = val
    return result


async def _audit_single_pack(employee_id: str) -> _facade().Dict[str, _facade().Any]:
    """对单个员工包构建 zip 并调沙盒审核，返回原始 audit 结果。"""
    from modstore_server.employee_ai_scaffold import build_employee_pack_zip
    from modstore_server.mod_scaffold_runner import (
        materialize_employee_pack_if_missing,
        modstore_library_path,
    )
    from modstore_server.package_sandbox_audit import run_package_audit_async

    materialize_employee_pack_if_missing(employee_id)
    pack_dir = modstore_library_path() / employee_id
    mf_path = pack_dir / "manifest.json"
    if not mf_path.is_file():
        return {
            "ok": False,
            "error": f"员工包目录不存在: {employee_id}",
            "dimensions": {},
            "summary": {"average": 0, "pass": False},
        }
    try:
        manifest = _facade().json.loads(mf_path.read_text(encoding="utf-8"))
        zip_bytes = build_employee_pack_zip(employee_id, manifest)
    except Exception as exc:
        return {
            "ok": False,
            "error": f"构建员工包失败: {exc}",
            "dimensions": {},
            "summary": {"average": 0, "pass": False},
        }
    try:
        return await run_package_audit_async(zip_bytes, {"artifact": "employee_pack"})
    except Exception as exc:
        _facade().logger.warning("audit failed employee=%s: %s", employee_id, exc)
        return {
            "ok": False,
            "error": str(exc),
            "dimensions": {},
            "summary": {"average": 0, "pass": False},
        }


async def _run_five_dim_audit(
    employee_id: str,
    per_dimension_ids: _facade().Optional[_facade().Dict[str, str]] = None,
    auto_dimension_ids: _facade().Optional[_facade().Dict[str, str]] = None,
) -> _facade().Dict[str, _facade().Any]:
    """五维合成审核：每个维度可独立指向不同员工包。

    合并优先级（后者覆盖前者）：
    1. 环境变量 ``MODSTORE_AUDIT_DIM_<DIM>_EMPLOYEE``
    2. ``auto_dimension_ids``（LLM 从评审池自动挑选，仅填补空缺）
    3. ``per_dimension_ids``（API / 人工显式指定）

    未配置的维度回退到主员工 employee_id 的静态审核得分。
    """
    env_defaults = _facade()._load_audit_dimension_env_defaults()
    effective_map: _facade().Dict[str, str] = {}
    effective_map.update(env_defaults)
    if auto_dimension_ids:
        for dim in _facade().AUDIT_DIMENSIONS:
            if str(effective_map.get(dim) or "").strip():
                continue
            v = str(auto_dimension_ids.get(dim) or "").strip()
            if v:
                effective_map[dim] = v
    if per_dimension_ids:
        effective_map.update(
            {k: v for (k, v) in per_dimension_ids.items() if k in _facade().AUDIT_DIMENSIONS and v}
        )
    pack_ids_needed: set[str] = {employee_id}
    for dim in _facade().AUDIT_DIMENSIONS:
        eid = effective_map.get(dim, employee_id)
        pack_ids_needed.add(eid)
    import asyncio

    raw_audits: _facade().Dict[str, _facade().Dict[str, _facade().Any]] = {}
    coros = {eid: _facade()._audit_single_pack(eid) for eid in pack_ids_needed}
    results = await asyncio.gather(*coros.values(), return_exceptions=True)
    for eid, res in zip(coros.keys(), results):
        if isinstance(res, Exception):
            raw_audits[eid] = {
                "ok": False,
                "error": str(res),
                "dimensions": {},
                "summary": {"average": 0, "pass": False},
            }
        else:
            raw_audits[eid] = res
    primary_audit = raw_audits[employee_id]
    merged_dims: _facade().Dict[str, _facade().Any] = {}
    for dim in _facade().AUDIT_DIMENSIONS:
        target_eid = effective_map.get(dim, employee_id)
        target_audit = raw_audits.get(target_eid, primary_audit)
        dim_data = (target_audit.get("dimensions") or {}).get(dim)
        if dim_data is not None:
            entry = dict(dim_data)
            if target_eid != employee_id:
                entry["_source_employee"] = target_eid
        else:
            fallback = (primary_audit.get("dimensions") or {}).get(dim)
            if fallback is not None:
                entry = dict(fallback)
                if target_eid != employee_id:
                    entry["reasons"] = list(entry.get("reasons") or []) + [
                        f"[分包 {target_eid} 审核失败，已回退到主员工]"
                    ]
                    entry["_source_employee"] = f"{target_eid}(fallback→{employee_id})"
            else:
                entry = {"score": 0, "reasons": ["审核数据缺失"]}
        merged_dims[dim] = entry
    scores = [int(merged_dims[d].get("score") or 0) for d in _facade().AUDIT_DIMENSIONS]
    average = round(sum(scores) / len(scores), 1) if scores else 0.0
    manifest_ok = int(merged_dims.get("manifest_compliance", {}).get("score") or 0) >= 40
    orig_manifest_err = bool(
        primary_audit.get("summary", {}).get("pass") is False
        and (not primary_audit.get("dimensions"))
    )
    passed = average >= 60 and manifest_ok and (not orig_manifest_err)
    return {
        "ok": True,
        "dimensions": merged_dims,
        "functional_tests": primary_audit.get("functional_tests") or [],
        "summary": {
            "average": average,
            "pass": passed,
            "artifact": (primary_audit.get("summary") or {}).get("artifact", "employee_pack"),
            "composite": bool(effective_map),
        },
    }
