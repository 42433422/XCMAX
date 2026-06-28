# Main Dirty Worktree Split

- Generated: 2026-06-29
- Target worktree: `/Users/a4243342/Desktop/XCMAX/.claude/worktrees/pedantic-leakey-5611d9`
- Branch: `main`
- Starting status: `main...origin/main [ahead 2]`
- Dirty entries: 76
- Rule: preserve feature-bearing branches and local work; do not delete or reset dirty worktrees.

## Summary

`main` is dirty for four different reasons that should not be merged together:

| queue | entries | action |
| --- | ---: | --- |
| Q0 runtime/index hygiene | 4 | untrack/ignore first; do not treat as product feature |
| Q1 FHD employee IM + Android surface | 25 | feature candidate; needs backend + Android tests |
| Q2 Retort engine hardening | 26 | feature candidate; remove runtime state from the same commit |
| Q3 MODstore employee runtime | 25 | feature candidate; separate product code from debug/verify evidence |

## Q0 Runtime/Index Hygiene

These are generated or local runtime files. They should be removed from Git tracking with `git rm --cached` after the ignore rules from `codex/git-hygiene-intake` are present. The local files should stay on disk.

- `packages/retort_engine/.retort/employee_queue.jsonl`
- `packages/retort_engine/.retort/llm_reviews.jsonl`
- `packages/retort_engine/.retort/retort_history.sqlite`
- `成都修茈科技有限公司/MODstore_deploy/modstore.db)`

Acceptance:

- `git ls-files packages/retort_engine/.retort .hvigor/outputs '成都修茈科技有限公司/MODstore_deploy/modstore.db)' | wc -l` returns `0`.
- Running Retort or MODstore locally may recreate files, but `git status` must not show them.

## Q1 FHD Employee IM + Android Surface

This looks like one product feature: employee IM / human question loop wired through backend APIs and Android screens.

Tracked files:

- `FHD/app/application/im_app_service.py`
- `FHD/app/db/init_db.py`
- `FHD/app/db/models/__init__.py`
- `FHD/app/fastapi_routes/mobile_api_extensions.py`
- `FHD/app/infrastructure/auth/dependencies.py`
- `FHD/app/infrastructure/session/session_manager.py`
- `FHD/app/legacy/routes/legacy_compat.py`
- `FHD/app/middleware/csrf.py`
- `FHD/mobile-android/app/build.gradle.kts`
- `FHD/mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/core/im/ImRepository.kt`
- `FHD/mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/core/im/ImWebSocketClient.kt`
- `FHD/mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/core/model/ApiModels.kt`
- `FHD/mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/core/network/ApiEndpoints.kt`
- `FHD/mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/core/network/FhdApi.kt`
- `FHD/mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/core/network/SseChatClient.kt`
- `FHD/mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/core/repository/SuperEmployeeRoutingPolicy.kt`
- `FHD/mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/core/repository/XcagiRepository.kt`
- `FHD/mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/navigation/AiCircleScreens.kt`
- `FHD/mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/navigation/Routes.kt`
- `FHD/mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/navigation/XcagiNavHost.kt`
- `FHD/mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/ui/AppViewModel.kt`

Untracked files:

- `FHD/ai_group_chat/groups.jsonl`
- `FHD/app/db/models/ai_employee.py`
- `FHD/app/fastapi_routes/employee_im_internal_api.py`
- `FHD/mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/navigation/EmployeeQuestionsScreen.kt`

Recommended intake:

1. Stage this group only.
2. Run focused backend route/model tests for employee IM.
3. Run Android compile/surface validation for the new screen and SSE client.
4. Commit as one feature if tests pass; otherwise split backend and Android.

## Q2 Retort Engine Hardening

This appears to be a real Retort feature/hardening set, mixed with Q0 runtime state.

Feature files:

- `packages/retort_engine/docs/retort_absorption_release_decision.json`
- `packages/retort_engine/docs/retort_competitor_runtime_comparison.json`
- `packages/retort_engine/docs/retort_operator_journey_replay.json`
- `packages/retort_engine/docs/retort_quality_gate_bundle.json`
- `packages/retort_engine/docs/retort_upstream_pr_ci_probe.json`
- `packages/retort_engine/retort_engine/cli.py`
- `packages/retort_engine/retort_engine/competitor_runtime_comparison.py`
- `packages/retort_engine/retort_engine/core.py`
- `packages/retort_engine/retort_engine/frontend/app.js`
- `packages/retort_engine/retort_engine/frontend/index.html`
- `packages/retort_engine/retort_engine/llm_absorption_evidence.py`
- `packages/retort_engine/retort_engine/pr_review.py`
- `packages/retort_engine/retort_engine/service.py`
- `packages/retort_engine/retort_engine/ui_features.py`
- `packages/retort_engine/retort_engine/ui_server.py`
- `packages/retort_engine/retort_engine/upstream_pr_ci_probe.py`
- `packages/retort_engine/tests/test_competitor_runtime_comparison.py`
- `packages/retort_engine/tests/test_core_review_score_matrix.py`
- `packages/retort_engine/tests/test_operator_journey_replay.py`
- `packages/retort_engine/tests/test_pr_review.py`
- `packages/retort_engine/tests/test_project_assessment.py`
- `packages/retort_engine/tests/test_retort_engine.py`
- `packages/retort_engine/tests/test_upstream_pr_ci_probe.py`

Recommended intake:

1. Exclude `.retort/` state from the commit.
2. Run the Retort focused tests changed in this queue.
3. Commit as a Retort feature only after the runtime docs are confirmed intentional.

## Q3 MODstore Employee Runtime

This looks like a feature set for employee runtime perception/classification/handoff, plus local debug and verification scripts.

Tracked product files:

- `成都修茈科技有限公司/MODstore_deploy/modstore_server/admin_employee_autonomy_api.py`
- `成都修茈科技有限公司/MODstore_deploy/modstore_server/employee_executor.py`
- `成都修茈科技有限公司/MODstore_deploy/modstore_server/employee_handoff.py`

Untracked product candidates:

- `成都修茈科技有限公司/MODstore_deploy/modstore_server/employee_human_report.py`
- `成都修茈科技有限公司/MODstore_deploy/modstore_server/employee_im_bridge.py`
- `成都修茈科技有限公司/MODstore_deploy/modstore_server/employee_path_guard.py`
- `成都修茈科技有限公司/MODstore_deploy/modstore_server/employee_perception_enricher.py`
- `成都修茈科技有限公司/MODstore_deploy/modstore_server/employee_scorecard.py`
- `成都修茈科技有限公司/MODstore_deploy/modstore_server/employee_self_evolution.py`
- `成都修茈科技有限公司/MODstore_deploy/modstore_server/employee_task_classifier.py`
- `成都修茈科技有限公司/MODstore_deploy/modstore_server/employee_verification.py`

Untracked evidence/debug candidates:

- `成都修茈科技有限公司/MODstore_deploy/debug_cognition_output.py`
- `成都修茈科技有限公司/MODstore_deploy/debug_llm_output.py`
- `成都修茈科技有限公司/MODstore_deploy/debug_phase_d_parse.py`
- `成都修茈科技有限公司/MODstore_deploy/test_all_employees.py`
- `成都修茈科技有限公司/MODstore_deploy/test_phase_d.py`
- `成都修茈科技有限公司/MODstore_deploy/test_results.json`
- `成都修茈科技有限公司/MODstore_deploy/verify_evolution_signal.py`
- `成都修茈科技有限公司/MODstore_deploy/verify_handoff.py`
- `成都修茈科技有限公司/MODstore_deploy/verify_one_employee.py`
- `成都修茈科技有限公司/MODstore_deploy/verify_perception_enricher.py`
- `成都修茈科技有限公司/MODstore_deploy/verify_s1.py`
- `成都修茈科技有限公司/MODstore_deploy/verify_s1_report.json`
- `成都修茈科技有限公司/MODstore_deploy/verify_task_classifier.py`

Recommended intake:

1. Commit product modules separately from debug/verify evidence.
2. Move durable verification into `tests/` if it should be long-lived.
3. Ignore or archive one-off `debug_*`, `verify_*`, and `test_results.json` files if they are only local run evidence.

## Execution Order

1. Land or selectively apply `codex/git-hygiene-intake` to stop new runtime noise.
2. Apply Q0 untrack in `main`; verify tracked runtime candidate count is `0`.
3. Intake Q1 FHD employee IM feature.
4. Intake Q3 MODstore employee runtime feature.
5. Intake Q2 Retort feature after Q0 is clean, because Retort currently has the highest artifact risk.
