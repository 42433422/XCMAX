# mypy: disable-error-code="attr-defined, no-any-return, union-attr, valid-type"
# ruff: noqa: E402, F401, I001
"""Time-rail derivation tail phase."""

from __future__ import annotations

import importlib

from modstore_server.operational_errors import RECOVERABLE_ERRORS


def _facade():
    return importlib.import_module("modstore_server.time_rail_workflow")


def _derive_from_sources_tail_phase_01(state):
    if state["digest"] is not None:
        state["created"] = _facade()._iso_or_none(getattr(state["digest"], "created_at", None))
        state["latest_digest_created"] = state["created"]
        state["day"] = str(getattr(state["digest"], "day", "") or "")
        state["record_id"] = int(getattr(state["digest"], "id", 0) or 0)
        state["latest_digest_record_id"] = state["record_id"]
        state["release_kind"] = str(getattr(state["digest"], "release_kind", "") or "daily")
        state["latest_release_kind"] = state["release_kind"]
        state["derived"]["daily-hub"] = _facade()._node_status_shell(
            "daily-hub",
            last_run=state["created"],
            ok=True,
            source="daily_digest_records",
            detail={
                "digest_id": state["record_id"],
                "day": state["day"],
                "release_kind": state["release_kind"],
            },
            observed=True,
        )
        state["derived"]["K"] = _facade()._node_status_shell(
            "K",
            last_run=state["created"],
            ok=bool(
                getattr(state["digest"], "body_html", "")
                or getattr(state["digest"], "body_text", "")
            ),
            source="daily_digest_records",
            detail={
                "digest_id": state["record_id"],
                "day": state["day"],
                "scope": "KPI/TLS/IMAP section",
            },
        )
        state["derived"]["P"] = _facade()._node_status_shell(
            "P",
            last_run=state["created"],
            ok=bool(getattr(state["digest"], "delivered", False)),
            source="daily_digest_records",
            detail={"digest_id": state["record_id"], "day": state["day"]},
        )
        state["derived"]["ASM"] = _facade()._node_status_shell(
            "ASM",
            last_run=state["created"],
            ok=bool(
                getattr(state["digest"], "body_html", "")
                or getattr(state["digest"], "body_text", "")
            ),
            source="daily_digest_records",
            detail={"digest_id": state["record_id"], "day": state["day"]},
        )
        state["derived"]["M"] = _facade()._node_status_shell(
            "M",
            last_run=state["created"],
            ok=bool(getattr(state["digest"], "meeting_minutes_html", "")),
            source="daily_digest_records",
            detail={"digest_id": state["record_id"], "day": state["day"]},
        )
        state["derived"]["V"] = _facade()._node_status_shell(
            "V",
            last_run=state["created"],
            ok=bool(
                getattr(state["digest"], "vibe_prep_updates_md", "")
                or getattr(state["digest"], "vibe_prep_patches_md", "")
            ),
            source="daily_digest_records",
            detail={
                "release_kind": state["release_kind"],
                "digest_id": state["record_id"],
            },
        )
        state["derived"]["KIND"] = _facade()._node_status_shell(
            "KIND",
            last_run=state["created"],
            ok=None,
            source="daily_digest_records",
            detail={
                "release_kind": state["release_kind"],
                "digest_id": state["record_id"],
            },
            observed=True,
            proof_status=(
                "decision_true"
                if state["release_kind"] in ("installer", "major")
                else "decision_false"
            ),
        )
        state["action_stats"] = _facade()._action_item_stats(
            day=state["day"], record_id=state["record_id"]
        )
        if state["action_stats"].get("ok"):
            state["derived"]["ACT"] = _facade()._node_status_shell(
                "ACT",
                last_run=state["created"],
                ok=True,
                source="daily_action_items",
                detail=state["action_stats"],
                observed=True,
            )
            state["patch_count"] = int((state["action_stats"].get("by_kind") or {}).get("patch", 0))
            state["update_count"] = int(
                (state["action_stats"].get("by_kind") or {}).get("update", 0)
            )
            state["derived"]["GAPS"] = _facade()._node_status_shell(
                "GAPS",
                last_run=state["created"],
                ok=True,
                source="daily_action_items",
                detail={
                    "patch_items": state["patch_count"],
                    "digest_id": state["record_id"],
                },
                observed=True,
            )
            state["derived"]["ROAD"] = _facade()._node_status_shell(
                "ROAD",
                last_run=state["created"],
                ok=True,
                source="daily_action_items",
                detail={
                    "update_items": state["update_count"],
                    "digest_id": state["record_id"],
                },
                observed=True,
            )
            state["merged"] = int((state["action_stats"].get("by_status") or {}).get("merged", 0))
            if state["merged"]:
                state["derived"]["WB_M"] = _facade()._node_status_shell(
                    "WB_M",
                    last_run=state["created"],
                    ok=True,
                    source="daily_action_items",
                    detail={
                        "merged_items": state["merged"],
                        "digest_id": state["record_id"],
                    },
                    observed=True,
                )
        state["line_dispatch"] = _facade()._json_obj(
            getattr(state["digest"], "vibe_prep_line_dispatch_json", "") or ""
        )
        if state["line_dispatch"]:
            state["latest_line_dispatch"] = state["line_dispatch"]
            state["derived"]["L"] = _facade()._node_status_shell(
                "L",
                last_run=state["created"],
                ok=state["line_dispatch"].get("ok") is not False,
                source="daily_digest.vibe_prep_line_dispatch",
                detail={
                    "digest_id": state["record_id"],
                    "line_meta": state["line_dispatch"].get("line_meta"),
                    "total_sections": state["line_dispatch"].get("total_sections"),
                },
                observed=True,
            )
        state["derived"]["ART"] = _facade()._node_status_shell(
            "ART",
            last_run=state["created"],
            ok=True,
            source="daily_digest_records",
            detail={
                "digest_id": state["record_id"],
                "has_meta": bool(getattr(state["digest"], "vibe_prep_meta_json", "")),
            },
            observed=True,
        )
        state["meta_raw"] = getattr(state["digest"], "vibe_prep_meta_json", "") or ""
        if state["meta_raw"]:
            try:
                state["meta"] = (
                    _facade().json.loads(state["meta_raw"])
                    if isinstance(state["meta_raw"], str)
                    else state["meta_raw"]
                )
                state["audit"] = (
                    (state["meta"] or {}).get("surface_audit")
                    if isinstance(state["meta"], dict)
                    else None
                )
                if isinstance(state["audit"], dict):
                    for state["lane"], state["nid"] in (
                        ("P-W", "SW"),
                        ("P-S", "SS"),
                        ("P-App", "SA"),
                    ):
                        state["lane_row"] = state["audit"].get(state["lane"]) or state["audit"].get(
                            state["lane"].replace("-", "")
                        )
                        if isinstance(state["lane_row"], dict):
                            state["derived"][state["nid"]] = _facade()._node_status_shell(
                                state["nid"],
                                last_run=state["created"],
                                ok=state["lane_row"].get("ok") is not False,
                                source="daily_digest.surface_audit",
                                detail=state["lane_row"],
                            )
                    state["ppt"] = (
                        state["audit"].get("ppt")
                        if isinstance(state["audit"].get("ppt"), dict)
                        else None
                    )
                    if state["ppt"]:
                        state["derived"]["PPTX"] = _facade()._node_status_shell(
                            "PPTX",
                            last_run=state["created"],
                            ok=state["ppt"].get("ok") is not False,
                            source="daily_digest.surface_audit",
                            detail=state["ppt"],
                        )
                state["orch"] = (
                    (state["meta"] or {}).get("orchestrator_audit")
                    if isinstance(state["meta"], dict)
                    else None
                )
                if isinstance(state["orch"], dict):
                    state["derived"]["ORCH"] = _facade()._status_from_block(
                        "ORCH", state["orch"], source="daily_digest.orchestrator_audit"
                    )
                    state["derived"]["BR"] = _facade()._node_status_shell(
                        "BR",
                        last_run=_facade()._iso_or_none(state["orch"].get("ran_at")),
                        ok=state["orch"].get("orchestrator_mode") in ("primary", "digest"),
                        source="daily_digest.orchestrator_audit",
                        detail=state["orch"],
                        observed=True,
                    )
            except RECOVERABLE_ERRORS:
                _facade().logger.debug("time_rail: surface_audit meta parse failed", exc_info=True)
        state["exec_raw"] = getattr(state["digest"], "vibe_line_execute_json", "") or ""
        if state["exec_raw"]:
            try:
                state["ex"] = (
                    _facade().json.loads(state["exec_raw"])
                    if isinstance(state["exec_raw"], str)
                    else state["exec_raw"]
                )
                if isinstance(state["ex"], dict):
                    state["derived"]["PARSE"] = _facade()._node_status_shell(
                        "PARSE",
                        last_run=state["created"],
                        ok=state["ex"].get("ok") is not False,
                        source="daily_digest.vibe_line_execute",
                        detail={
                            "mode": state["ex"].get("mode"),
                            "digest_id": state["record_id"],
                        },
                    )
                    state["runs"] = (
                        state["ex"].get("runs") if isinstance(state["ex"].get("runs"), dict) else {}
                    )
                    state["phase_a"] = (
                        state["ex"].get("phase_a")
                        if isinstance(state["ex"].get("phase_a"), dict)
                        else {}
                    )
                    state["phase_b"] = (
                        state["ex"].get("phase_b")
                        if isinstance(state["ex"].get("phase_b"), dict)
                        else {}
                    )
                    state["phase_c"] = (
                        state["ex"].get("phase_c")
                        if isinstance(state["ex"].get("phase_c"), dict)
                        else {}
                    )
                    state["phase_c_pipeline"] = (
                        state["ex"].get("phase_c_pipeline")
                        if isinstance(state["ex"].get("phase_c_pipeline"), dict)
                        else {}
                    )
                    state["latest_phase_c"] = state["phase_c"]
                    state["latest_phase_c_pipeline"] = state["phase_c_pipeline"]
                    state["ps_run"] = (
                        (state["phase_a"].get("line_results") or {}).get("P-S")
                        or state["runs"].get("P-S")
                        or {}
                    )
                    state["app_run"] = (
                        (state["phase_a"].get("line_results") or {}).get("P-App")
                        or state["runs"].get("P-App")
                        or {}
                    )
                    if state["ps_run"]:
                        state["derived"]["PSA"] = _facade()._status_from_block(
                            "PSA", state["ps_run"], source="daily_digest.phase_a.P-S"
                        )
                    if state["app_run"]:
                        state["derived"]["APPA"] = _facade()._status_from_block(
                            "APPA",
                            state["app_run"],
                            source="daily_digest.phase_a.P-App",
                        )
                    if state["phase_a"]:
                        state["derived"]["WB_D"] = _facade()._status_from_block(
                            "WB_D", state["phase_a"], source="daily_digest.phase_a"
                        )
                    for state["source_nid"], state["mapped_nid"] in (("PSA", "P2S"),):
                        if (
                            state["source_nid"] in state["derived"]
                            and state["mapped_nid"] not in state["derived"]
                        ):
                            state["derived"][state["mapped_nid"]] = _facade()._derive_mapped_node(
                                state["mapped_nid"],
                                state["derived"][state["source_nid"]],
                                source=f"time_rail.derive.{state['source_nid']}",
                                detail={
                                    "record_id": state["record_id"],
                                    "release_kind": state["release_kind"],
                                },
                            )
                    for state["line_key"], state["nid"] in (
                        ("P-W", "PW"),
                        ("P-App", "APPB"),
                        ("S-R", "SR"),
                    ):
                        state["line_block"] = (state["phase_b"].get("line_results") or {}).get(
                            state["line_key"]
                        ) or {}
                        if state["line_block"]:
                            state["derived"][state["nid"]] = _facade()._status_from_block(
                                state["nid"],
                                state["line_block"],
                                source=f"daily_digest.phase_b.{state['line_key']}",
                            )
                    _facade()._ensure_p2_line_mappings(
                        state["derived"],
                        record_id=state["record_id"],
                        release_kind=state["release_kind"],
                    )
                    if "APPB" not in state["derived"] and "APPA" in state["derived"]:
                        state["derived"]["APPB"] = _facade()._decision_not_taken_status(
                            "APPB",
                            last_run=_facade()._iso_or_none(
                                state["derived"]["APPA"].get("last_run")
                            ),
                            source="daily_digest.phase_a.P-App",
                            reason="phase_b_app_updates_not_scheduled",
                            detail={
                                "record_id": state["record_id"],
                                "release_kind": state["release_kind"],
                            },
                        )
                    if state["phase_b"]:
                        state["derived"]["ORCH"] = state["derived"].get(
                            "ORCH"
                        ) or _facade()._status_from_block(
                            "ORCH", state["phase_b"], source="daily_digest.phase_b"
                        )
                    if state["phase_c_pipeline"]:
                        state["step_ids"] = list(
                            state["phase_c_pipeline"].get("executed_steps")
                            or state["phase_c_pipeline"].get("step_ids")
                            or state["phase_c_pipeline"].get("planned_steps")
                            or []
                        )
                        for state["step"] in ("P3", "P4", "P5", "P6", "P7", "P8", "P9"):
                            if state["step"] in state["step_ids"]:
                                state["derived"][state["step"]] = _facade()._status_from_block(
                                    state["step"],
                                    state["phase_c_pipeline"],
                                    source="daily_digest.phase_c_pipeline",
                                    detail={
                                        "step": state["step"],
                                        "step_ids": state["step_ids"],
                                    },
                                )
                        if any(
                            (state["step"] in state["step_ids"] for state["step"] in ("P5", "P6"))
                        ):
                            state["derived"]["CANARY"] = _facade()._status_from_block(
                                "CANARY",
                                state["phase_c_pipeline"],
                                source="daily_digest.phase_c_pipeline",
                                detail={
                                    "step_ids": state["step_ids"],
                                    "strategy": "staging-canary-production",
                                },
                            )
                        if state["phase_c_pipeline"].get("rollback"):
                            state["derived"]["ROLLBACK"] = _facade()._status_from_block(
                                "ROLLBACK",
                                state["phase_c_pipeline"].get("rollback") or {},
                                source="daily_digest.phase_c_pipeline.rollback",
                            )
                    if state["phase_c"]:
                        state["step_results"] = (
                            state["phase_c"].get("steps")
                            if isinstance(state["phase_c"].get("steps"), list)
                            else []
                        )
                        state["step_map"] = {
                            str(state["s"].get("step") or ""): state["s"]
                            for state["s"] in state["step_results"]
                            if isinstance(state["s"], dict)
                        }
                        for state["source_step"], state["nid"] in (
                            ("P9", "P9I"),
                            ("P5", "P5I"),
                            ("P6", "P6I"),
                        ):
                            if state["source_step"] in state["step_map"]:
                                state["derived"][state["nid"]] = _facade()._status_from_block(
                                    state["nid"],
                                    state["step_map"][state["source_step"]],
                                    source="daily_digest.phase_c.installer_chain",
                                )
                        if state["phase_c"].get("fastgate"):
                            state["derived"]["FASTGATE"] = _facade()._status_from_block(
                                "FASTGATE",
                                state["phase_c"].get("fastgate") or {},
                                source="daily_digest.phase_c.fastgate",
                            )
                        if state["phase_c"].get("download_release"):
                            state["derived"]["DLSSOT"] = _facade()._status_from_block(
                                "DLSSOT",
                                state["phase_c"].get("download_release") or {},
                                source="daily_digest.phase_c.download_release",
                            )
                        if state["phase_c"].get("rollback"):
                            state["derived"]["ROLLBACK"] = _facade()._status_from_block(
                                "ROLLBACK",
                                state["phase_c"].get("rollback") or {},
                                source="daily_digest.phase_c.rollback",
                            )
            except RECOVERABLE_ERRORS:
                pass
    return None
