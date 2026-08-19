# ruff: noqa
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.employee_bench")


async def run_and_score_bench(
    employee_id: str,
    task_list: _facade().List[_facade().Dict[str, _facade().Any]],
    *,
    db: _facade().Session,
    user: _facade().User,
    bench_llm_override: _facade().Optional[_facade().Tuple[str, str]] = None,
    per_dimension_ids: _facade().Optional[_facade().Dict[str, str]] = None,
) -> _facade().Dict[str, _facade().Any]:
    """执行全部测试任务、量化打分、五维审核，返回综合报告。

    bench_llm_override=(provider, model) 时，员工执行阶段的认知层使用该
    平台模型而非 manifest 中配置的模型（不读用户 BYOK）。

    per_dimension_ids={dim: employee_id} 时，各维度由指定员工包独立审核；
    未配置或员工包不存在的维度回退到 employee_id 主员工的静态审核结果。

    返回结构：
    {
        tasks_result: [{level, task_id, task_desc, ok, cost_tokens, duration_ms, score}],
        level_scores: {1: float, ..., 5: float},
        overall_score: float,
        audit: {...},          # run_package_audit_async 完整返回
        passed: bool,
    }
    """
    import asyncio

    tasks_result: _facade().List[_facade().Dict[str, _facade().Any]] = []
    level_results: _facade().Dict[int, _facade().List[_facade().Dict[str, _facade().Any]]] = {
        lv: [] for lv in range(1, 6)
    }
    for level_group in task_list:
        lv = int(level_group.get("level") or 0)
        if lv < 1 or lv > 5:
            continue
        for task in level_group.get("tasks") or []:
            task_id = str(task.get("id") or f"{lv}-?")
            task_desc = str(task.get("task_desc") or "").strip()
            if not task_desc:
                continue
            run_result = await asyncio.to_thread(
                _facade()._run_single_task, employee_id, task_desc, user.id, bench_llm_override
            )
            eff = _facade()._efficiency_factor(run_result["cost_tokens"])
            heuristic = 100.0 * (1.0 if run_result["ok"] else 0.0) * eff
            entry = {
                "level": lv,
                "task_id": task_id,
                "task_desc": task_desc,
                "ok": run_result["ok"],
                "cost_tokens": run_result["cost_tokens"],
                "duration_ms": run_result["duration_ms"],
                "heuristic_score": round(heuristic, 1),
                "score": round(heuristic, 1),
                "output_preview": run_result.get("output_preview") or "",
            }
            tasks_result.append(entry)
            level_results[lv].append(run_result)
    scoring_meta: _facade().Dict[str, _facade().Any] = {"method": "heuristic_ok_token_efficiency"}
    if bench_llm_override:
        (prov, mdl) = bench_llm_override
        rubric_items = [
            {
                "task_id": e["task_id"],
                "level": e["level"],
                "task_desc": e["task_desc"],
                "execution_ok": e["ok"],
                "output_excerpt": (e.get("output_preview") or "")[:1200],
            }
            for e in tasks_result
        ]
        (rubric_raw, rubric_err) = await _facade()._llm_rubric_scores_platform(
            prov, mdl, rubric_items
        )
        expected_ids = {e["task_id"] for e in tasks_result}
        rubric_map = _facade()._align_rubric_keys(rubric_raw, expected_ids)
        scoring_meta = {
            "method": "llm_rubric_platform",
            "provider": prov,
            "model": mdl,
            "rubric_raw_returned": len(rubric_raw),
            "rubric_aligned": len(rubric_map),
            "tasks_expected": len(expected_ids),
        }
        if rubric_err:
            scoring_meta["rubric_warning"] = rubric_err
        if rubric_map:
            missed = expected_ids - set(rubric_map.keys())
            if missed:
                scoring_meta["rubric_incomplete_task_ids"] = sorted(missed)
            for e in tasks_result:
                tid = e["task_id"]
                if tid in rubric_map:
                    e["score"] = round(rubric_map[tid], 1)
                    e["score_source"] = "llm_rubric"
                else:
                    e["score"] = round(min(float(e["heuristic_score"]), 35.0), 1)
                    e["score_source"] = "rubric_missing_penalty"
            vals = list(rubric_map.values())
            all_near_max = bool(vals) and all((float(v) >= 98.0 for v in vals))
            mostly_blank_out = sum(
                (1 for e in tasks_result if len((e.get("output_preview") or "").strip()) < 15)
            ) >= max(1, (len(tasks_result) + 1) // 2)
            if all_near_max and mostly_blank_out:
                scoring_meta["suspect_rubric_inflated"] = True
                for e in tasks_result:
                    if e.get("score_source") == "llm_rubric":
                        e["score"] = round(min(float(e["score"]), 55.0), 1)
                        e["score_note"] = "输出过短，抑制裁判虚高"
        else:
            scoring_meta["method"] = "heuristic_ok_token_efficiency"
            scoring_meta["rubric_failed"] = True
            for e in tasks_result:
                e["score"] = round(min(float(e["heuristic_score"]), 45.0), 1)
                e["score_source"] = "rubric_failed_capped"
        level_scores = _facade()._level_scores_from_entries(tasks_result)
        overall_score = round(_facade()._weighted_overall(level_scores), 1)
    else:
        level_scores = {
            lv: round(_facade()._score_level(results), 1) for (lv, results) in level_results.items()
        }
        overall_score = round(_facade()._weighted_overall(level_scores), 1)
    explicit_dims = {
        k: v
        for (k, v) in (per_dimension_ids or {}).items()
        if k in _facade().AUDIT_DIMENSIONS and str(v or "").strip()
    }
    (auto_dims, reviewer_sel_meta) = await _facade().resolve_auto_dimension_reviewers(
        employee_id,
        *_facade()._read_employee_brief(employee_id),
        bench_llm_override,
        explicit_per_dimension=explicit_dims,
    )
    audit = await _facade()._run_five_dim_audit(
        employee_id, explicit_dims or None, auto_dimension_ids=auto_dims
    )
    audit_passed = bool(audit.get("summary", {}).get("pass", False))
    peer = await _facade()._run_pack_peer_review_optional(
        employee_id, db=db, user=user, bench_llm_override=bench_llm_override
    )
    peer_blocks_pass = False
    if peer and (not peer.get("skipped")):
        audit = dict(audit)
        audit["pack_peer_review"] = peer
        if _facade()._peer_review_gate_enabled() and (not peer.get("skipped")):
            if not peer.get("ok"):
                peer_blocks_pass = True
            elif peer.get("missing_machine_score"):
                peer_blocks_pass = True
            elif not peer.get("pass_peer"):
                peer_blocks_pass = True
    passed = (
        overall_score >= _facade()._PASS_OVERALL_SCORE and audit_passed and (not peer_blocks_pass)
    )
    six_dimension: _facade().Optional[_facade().Dict[str, _facade().Any]] = None
    six_dimension_llm_meta: _facade().Optional[_facade().Dict[str, _facade().Any]] = None
    if bench_llm_override:
        try:
            from modstore_server.catalog_quality import pipeline_label_from_pack, run_pack_validate
            from modstore_server.employee_six_dimension import compute_six_dimension_report
            from modstore_server.employee_six_dimension_llm import (
                enrich_six_dimension_report_with_llm,
            )
            from modstore_server.mod_scaffold_runner import (
                materialize_employee_pack_if_missing,
                modstore_library_path,
            )

            materialize_employee_pack_if_missing(employee_id)
            pack_dir = modstore_library_path() / employee_id
            (brief, _panel) = _facade()._read_employee_brief(employee_id)
            if pack_dir.is_dir():
                pipeline_label = pipeline_label_from_pack(pack_dir, brief)
                val = await run_pack_validate(pack_dir=pack_dir, brief=brief)
                validate_errors = list(val.get("validate_errors") or [])
                baseline = compute_six_dimension_report(
                    pack_dir=pack_dir,
                    pipeline_label=pipeline_label,
                    routing_brief=brief,
                    validate_errors=validate_errors,
                    catalog_registered=False,
                    employee_target="pack_only",
                    standalone_smoke_ok=True,
                )
                bench_summary = {
                    "overall_score": overall_score,
                    "level_scores": level_scores,
                    "tasks_total": len(tasks_result),
                    "tasks_ok": sum((1 for e in tasks_result if e.get("ok"))),
                    "sample_tasks": [
                        {
                            "level": e.get("level"),
                            "ok": e.get("ok"),
                            "score": e.get("score"),
                            "task_desc": (e.get("task_desc") or "")[:120],
                        }
                        for e in tasks_result[:6]
                    ],
                }
                (six_dimension, six_dimension_llm_meta) = (
                    await enrich_six_dimension_report_with_llm(
                        baseline,
                        pack_dir=pack_dir,
                        target_employee_id=employee_id,
                        pipeline_label=pipeline_label,
                        routing_brief=brief,
                        validate_errors=validate_errors,
                        bench_summary=bench_summary,
                        user_id=int(getattr(user, "id", 0) or 0),
                        bench_llm_override=bench_llm_override,
                        require_llm=True,
                    )
                )
        except Exception as exc:
            _facade().logger.warning("bench six_dimension LLM failed for %s: %s", employee_id, exc)
            six_dimension_llm_meta = {"llm_error": str(exc)[:300]}
    out: _facade().Dict[str, _facade().Any] = {
        "tasks_result": tasks_result,
        "level_scores": level_scores,
        "overall_score": overall_score,
        "audit": audit,
        "passed": passed,
        "scoring": scoring_meta,
        "reviewer_selection": reviewer_sel_meta,
        "six_dimension": six_dimension,
        "six_dimension_llm_meta": six_dimension_llm_meta,
    }
    return out
