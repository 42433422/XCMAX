# Evidence: Retort Metric-Search × Evolution Ledger Bridge

**Date**: 2026-07-29  
**Scope**: P0 Retort `metric-search` engine + P1 `evolution_decision_ledger` bridge  
**Status**: unit + dry-run verified; heldout oracle continuous run still open

## What landed

| Layer | Artifact |
|-------|----------|
| Retort engine | `packages/retort_engine/retort_engine/metric_search.py` |
| Retort CLI | `retort metric-search` |
| Retort tests | `packages/retort_engine/tests/test_metric_search.py` (8 passed) |
| Eval contract | `employee_pack_proposal.extract_eval_spec` / `validate_eval_spec` |
| Ledger | `FHD/scripts/autonomy/evolution_decision_ledger.py` modes + events |
| L4 gap | `p1-metric-search` in `autonomyL4Readiness.ts` (status: partial) |

## Commands run

```bash
# Retort unit tests
cd packages/retort_engine && PYTHONPATH=. python3 -m pytest tests/test_metric_search.py -q
# → 8 passed

# Proposal eval contract tests
cd 成都修茈科技有限公司/MODstore_deploy && python3 -m pytest \
  tests/test_employee_pack_eval_spec.py \
  tests/test_employee_pack_proposal_scaffold.py \
  tests/test_propose_employee_pack.py -q
# → passed

# Ledger dry-run with Retort implement mode
MODSTORE_EVOLUTION_LEDGER_PATH=/tmp/evol-ledger-test.jsonl \
EVOLUTION_IMPLEMENT_MODE=retort-metric-search \
python3 FHD/scripts/autonomy/evolution_decision_ledger.py dry-run
```

## Dry-run trace (retort-metric-search)

Observed event types on one `trace_id`:

1. `signal_detected` (legacy_usage synthetic)
2. `proposal_generated` (eval_metric=recall)
3. `issue_opened` (dry-run)
4. `metric_search_started`
5. `metric_search_finished` (`best_score=0.75`, tree under `packages/retort_engine/.retort/metric_search/ledger-*`)
6. `implement_succeeded`
7. `pack_listed` (`closed_loop_completed`)

Default-mode dry-run (without `EVOLUTION_IMPLEMENT_MODE`) still completes the original 5-step path.

## Boundaries respected

- No changes to `self_maintenance_loop_runner` / CVM autonomy policies
- No WeCo runtime dependency
- Eval parse failure fails the trial (no LLM self-score substitute)

## Follow-ups

1. Non-dry-run `retort metric-search` against `heldout_oracle.resolved_rate`
2. Keep `p1-metric-search` partial until 7-day ledger observation
3. Optional steerable mid-run UI (explicitly out of V1)
