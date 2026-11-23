"""在职训练：把真实失败沉淀为回归用例，用 promptfoo 验证 prompt 改造。

设计原则：不自研评测引擎。本模块只负责三件事——挖掘失败、生成回归集、
把 promptfoo 的结果翻译成「改还是不改」的判定。
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import sys
import tempfile
from collections import defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from modstore_server.incident_team_handler_digest import redact_text

DEFAULT_MIN_COUNT = 2
DEFAULT_DAYS = 14
PROMPTFOO_VERSION = "0.126.0"
_CORPUS_SCHEMA = "xcagi.capability-training.corpus.encrypted/v1"
STRUCTURED_SURFACES = {"workflow_nl_prompt", "rag_context_prompt"}
_RUBRIC = (
    "回答必须包含约定结构（JSON 或指定标记），并且不得声称未经回执验证的"
    "完成、支付、部署、QA 或恢复；缺失信息要明确说明。"
)


def training_identity(record):
    surface = record.get("surface", "employee_prompt")
    resource = (
        record.get("employee_id") if surface == "employee_prompt" else record.get("resource_id")
    )
    if surface == "workflow_nl_prompt" and resource == "workflow_nl_generator":
        return surface, resource
    if surface == "rag_context_prompt" and resource == "employee_rag_context":
        return surface, resource
    if surface == "employee_prompt" and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", str(resource or "")):
        return surface, resource
    raise ValueError("invalid_training_surface")


def prompt_from_source(source, *, surface):
    if surface == "employee_prompt":
        return source
    if surface not in STRUCTURED_SURFACES:
        raise ValueError("invalid_training_surface")
    symbol = "RAG_SYSTEM_PROMPT" if surface == "rag_context_prompt" else "SYSTEM_PROMPT"
    values = [
        node.value.value
        for node in ast.parse(source).body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == symbol for target in node.targets)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    ]
    if len(values) != 1:
        raise ValueError("training_prompt_symbol_unbound")
    return values[0]


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _failure_of(record: dict[str, Any]) -> dict[str, Any] | None:
    if str(record.get("status") or "").lower() != "failed":
        return None
    try:
        surface, resource = training_identity(record)
    except ValueError:
        return None
    error = redact_text(record.get("error") or record.get("failure_reason") or "", 2000).strip()
    if not error:
        return None
    return {
        "surface": surface,
        "resource_id": resource,
        **(
            {"employee_id": resource}
            if surface == "employee_prompt"
            else {
                key: record[key]
                for key in (
                    "generation_context",
                    "prompt_sha256",
                    "workflow_id",
                    "user_id",
                    "validation_errors",
                )
                if key in record
            }
        ),
        "failure_reason": error,
        "step": record.get("step") or "",
        "task": (
            str(record.get("task_excerpt") or record.get("report_excerpt") or "")[:20000]
            if surface in STRUCTURED_SURFACES
            else redact_text(record.get("task_excerpt") or record.get("report_excerpt") or "", 2000)
        ),
        "timestamp": record.get("timestamp") or "",
        "run_id": record.get("run_id") or "",
    }


def cluster_failures(
    records: Iterable[dict[str, Any]],
    *,
    days: int = DEFAULT_DAYS,
    min_count: int = DEFAULT_MIN_COUNT,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    cutoff = (now or datetime.now(UTC)) - timedelta(days=max(1, days))
    groups: dict[tuple, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        item = _failure_of(record)
        if not item:
            continue
        seen_at = _parse_time(item["timestamp"])
        if seen_at is not None and seen_at < cutoff:
            continue
        groups[(*training_identity(item), item["failure_reason"][:160])].append(item)
    clusters = []
    for (surface, resource, reason), items in groups.items():
        if len(items) < max(1, min_count):
            continue
        clusters.append(
            {
                "surface": surface,
                "resource_id": resource,
                **({"employee_id": resource} if surface == "employee_prompt" else {}),
                "failure_reason": reason,
                "count": len(items),
                "samples": items[:20],
            }
        )
    clusters.sort(key=lambda row: (-row["count"], *training_identity(row)))
    return clusters


def mine(
    ledger_path: Path, *, days: int = DEFAULT_DAYS, min_count: int = DEFAULT_MIN_COUNT
) -> list[dict[str, Any]]:
    from modstore_server.rag_prompt_feedback import failure_records as rag_failures
    from modstore_server.workflow_nl_training import failure_records

    records = outbox_failures(days=days) + failure_records(days=days) + rag_failures(days=days)
    for line in (
        ledger_path.read_bytes().decode("utf-8").splitlines() if ledger_path.is_file() else []
    ):
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            records.append(row)
    return cluster_failures(records, days=days, min_count=min_count)


def outbox_failures(*, days=DEFAULT_DAYS):
    """Reuse real product observations without exporting task text or customer identity."""
    from sqlalchemy import select

    from modstore_server.customer_service_tools import json_loads
    from modstore_server.models import OutboxEvent, get_session_factory

    records = []
    if not os.environ.get("MODSTORE_RETORT_GROWTHBOOK_URL"):
        return records
    with get_session_factory()() as db:
        rows = db.scalars(
            select(OutboxEvent)
            .where(
                OutboxEvent.event_name == "experiment.observed",
                OutboxEvent.created_at >= datetime.now(UTC) - timedelta(days=max(1, days)),
            )
            .order_by(OutboxEvent.id.desc())
            .limit(10000)
        )
        for row in rows:
            observation = json_loads(row.payload_json, {})
            if (
                observation.get("success") is not False
                or observation.get("surface") != "employee_prompt"
                or observation.get("failure_kind") != "prompt"
            ):
                continue
            records.append(
                {
                    "status": "failed",
                    "employee_id": observation["resource_id"],
                    "error": "observed_prompt_execution_failed",
                    "step": "cognition",
                    "timestamp": observation["completed_at"],
                    "run_id": observation["observation_id"],
                }
            )
    return records


def _case_id(cluster: dict[str, Any], sample: dict[str, Any]) -> str:
    surface, resource = training_identity(cluster)
    raw = f"{resource}|{cluster['failure_reason']}|{sample.get('task', '')}"
    if surface != "employee_prompt":
        raw += f"|{surface}|{json.dumps(sample.get('generation_context'), sort_keys=True)}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _corpus_cases(path: Path, additions=()) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Keep original reproductions private; migrate legacy records without changing their identity."""
    from modstore_server.llm_crypto import decrypt_secret, encrypt_secret

    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock_path = path.parent / ".capability-corpus.lock"
    for candidate in (path, lock_path):
        if candidate.is_symlink():
            raise ValueError("training corpus cannot be a symbolic link")
    descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(descriptor, "a+", encoding="utf-8") as lock:
        if hasattr(os, "fchmod"):
            os.fchmod(lock.fileno(), 0o600)
        if sys.platform == "win32":
            import msvcrt

            if os.fstat(lock.fileno()).st_size == 0:
                lock.write(" ")
                lock.flush()
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        rows, legacy = [], False
        try:
            descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        except FileNotFoundError:
            lines = []
        else:
            with os.fdopen(descriptor, "r", encoding="utf-8") as source:
                if hasattr(os, "fchmod"):
                    os.fchmod(source.fileno(), 0o600)
                lines = source.readlines()
        for line in lines:
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError("invalid_training_corpus")
            if row.get("schema") == _CORPUS_SCHEMA and isinstance(row.get("ciphertext"), str):
                row = json.loads(decrypt_secret(row["ciphertext"]))
            elif "schema" in row or "ciphertext" in row:
                raise ValueError("invalid_training_corpus")
            else:
                legacy = True
            if (
                not isinstance(row, dict)
                or not isinstance(row.get("case_id"), str)
                or not row["case_id"]
                or not isinstance(row.get("task"), str)
            ):
                raise ValueError("invalid_training_corpus")
            rows.append(row)
        existing = {row["case_id"] for row in rows}
        written = []
        for row in additions:
            if row["case_id"] not in existing:
                rows.append(row)
                written.append(row)
                existing.add(row["case_id"])
        if legacy or written:
            # Encrypt every record before touching the original file. Missing or
            # incorrect keys and damaged records must never discard old samples.
            encrypted = [
                json.dumps(
                    {
                        "schema": _CORPUS_SCHEMA,
                        "ciphertext": encrypt_secret(json.dumps(row, ensure_ascii=False)),
                    },
                    sort_keys=True,
                )
                + "\n"
                for row in rows
            ]
            fd, temporary = tempfile.mkstemp(prefix=".training-corpus-", dir=path.parent)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.writelines(encrypted)
                    handle.flush()
                    os.fsync(handle.fileno())
                if path.is_symlink():
                    raise ValueError("training corpus cannot be a symbolic link")
                os.replace(temporary, path)
            finally:
                Path(temporary).unlink(missing_ok=True)
        return rows, written


def load_cases(path: Path) -> list[dict[str, Any]]:
    """Decrypt private training input, migrating legacy plaintext under the same write lock."""
    return _corpus_cases(path)[0]


def append_cases(
    corpus_dir: Path,
    clusters: list[dict[str, Any]],
    *,
    max_per_cluster: int = 3,
) -> list[dict[str, Any]]:
    """只追加新用例，重复失败不会反复写同一条。"""
    from modstore_server.workflow_training_dataset import is_business_case

    written: list[dict[str, Any]] = []
    for cluster in clusters:
        surface, resource = training_identity(cluster)
        key = resource if surface == "employee_prompt" else f"{surface}-{resource}"
        path = corpus_dir / f"{key}.jsonl"
        limit = (
            20 if any(is_business_case(item) for item in cluster["samples"]) else max_per_cluster
        )
        additions = [
            {
                "case_id": _case_id(cluster, sample),
                "surface": surface,
                "resource_id": resource,
                **(
                    {"generation_context": sample["generation_context"]}
                    if surface in STRUCTURED_SURFACES
                    else {}
                ),
                "failure_reason": cluster["failure_reason"],
                "task": sample["task"],
                "source_run": sample.get("run_id") or "",
                "created_at": datetime.now(UTC).isoformat(),
            }
            for sample in cluster["samples"][:limit]
            if sample.get("task")  # An observation is not a reproduction input.
        ]
        written.extend(_corpus_cases(path, additions)[1])
    return written


def select_pack(packs_dir: Path, employee_id: str) -> Path | None:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", employee_id):
        raise ValueError("invalid_training_employee")
    candidates = sorted(packs_dir.glob(f"{employee_id}@*"))
    for path in reversed(candidates):
        if (path / "prompt.txt").is_file():
            return path
    return None


def _yaml_str(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _prompt_document(prompt, surface):
    if surface == "employee_prompt":
        return "{{task}}\n\n" + prompt
    if surface == "rag_context_prompt":
        from modstore_server.rag_prompt_feedback import prompt_document

        return prompt_document(prompt)
    if surface != "workflow_nl_prompt" or "{% endraw" in prompt:
        raise ValueError("invalid_training_prompt_template")
    return (
        "{% raw %}"
        + json.dumps([{"role": "system", "content": prompt}], ensure_ascii=False)[:-1]
        + '{% endraw %},{"role":"user","content":{{ task | dump }}}]'
    )


def _prompt_value(document, surface):
    if surface == "rag_context_prompt":
        from modstore_server.rag_prompt_feedback import prompt_value

        return prompt_value(document)
    if surface == "employee_prompt":
        if not document.startswith("{{task}}\n\n"):
            raise ValueError("training_prompt_hash_mismatch")
        return document.removeprefix("{{task}}\n\n")
    suffix = '{% endraw %},{"role":"user","content":{{ task | dump }}}]'
    if not document.startswith("{% raw %}") or not document.endswith(suffix):
        raise ValueError("training_prompt_hash_mismatch")
    value = json.loads(document[len("{% raw %}") : -len(suffix)] + "]")[0]["content"]
    if document != _prompt_document(value, surface):
        raise ValueError("training_prompt_hash_mismatch")
    return value


def _workflow_validation_hashes(*, business=False):
    names = (
        "workflow_nl_training.py",
        "workflow_nl_apply.py",
        "workflow_nl_operations.py",
        "workflow_engine.py",
        "workflow_engine_workflowengine_mixin01__workflowenginepart01mixin_mixin01.py",
    )
    if business:
        names += (
            "capability_trainer.py",
            "retort_experiment_surfaces.py",
            "workflow_training_dataset.py",
            "workflow_training_replay.py",
            "workflow_training_artifact_verification.py",
            "workflow_customer_delivery.py",
            "workflow_variables.py",
            "workflow_engine_workflowengine_mixin01.py",
            "workflow_engine_workflowengine_mixin02.py",
            "workflow_engine_workflowengine_mixin01__workflowenginepart01mixin_mixin02.py",
            "self_maintenance_subprocess.py",
            "employee_runtime.py",
            "employee_runtime_policy.py",
            "strategic_execution_contract.py",
            "services/employee.py",
            "employee_executor.py",
            "employee_executor_merged.py",
            "employee_executor_merged_mod1.py",
            "employee_executor_merged_mod2.py",
        )
    hashes = {name: _file_hash(Path(__file__).parent / name) for name in names}
    if business:
        support = "FHD/app/mod_sdk/file_employee_support.py"
        hashes[support] = _file_hash(Path(__file__).resolve().parents[3] / support)
        for name in ("promptfoo_sandbox.mjs", "opencode_agent.mjs"):
            wrapper = f"FHD/scripts/autonomy/runtime_tools/{name}"
            hashes[wrapper] = _file_hash(Path(__file__).resolve().parents[3] / wrapper)
    return hashes


def _validation(surface, *, business=False):
    if surface == "rag_context_prompt":
        from modstore_server.rag_prompt_feedback import get_assert
        from modstore_server.retort_experiment_surfaces import RAG_MEASUREMENT

        names = ("rag_prompt_feedback.py", "rag_service.py", "employee_executor_merged_mod1.py")
        return (
            RAG_MEASUREMENT,
            {n: _file_hash(Path(__file__).with_name(n)) for n in names},
            get_assert,
            "rag_prompt_feedback.py",
        )
    from modstore_server.workflow_nl_training import get_assert
    from modstore_server.workflow_training_dataset import BUSINESS_SCOPE

    return (
        BUSINESS_SCOPE if business else "workflow_generation_static_validation",
        _workflow_validation_hashes(business=business),
        get_assert,
        "workflow_nl_training.py",
    )


def build_config(
    *,
    out_dir: Path,
    baseline_prompt: str,
    candidate_prompt: str,
    cases: list[dict[str, Any]],
    surface: str = "employee_prompt",
) -> dict[str, str]:
    from modstore_server.workflow_training_dataset import (
        is_business_case,
        partition_cases,
        validate_business_budget,
    )

    workflow = surface in STRUCTURED_SURFACES
    if surface not in {"employee_prompt", *STRUCTURED_SURFACES}:
        raise ValueError("invalid_training_surface")
    if not 1 <= len(cases) <= 20 or any(
        not isinstance(case.get("task"), str)
        or not 1 <= len(case["task"].strip()) <= (20000 if workflow else 2000)
        or (workflow and not isinstance(case.get("generation_context"), dict))
        for case in cases
    ):
        raise ValueError("training_reproduction_cases_required")
    business = surface == "workflow_nl_prompt" and any(is_business_case(case) for case in cases)
    cases = partition_cases(cases) if business else cases
    if business:
        validate_business_budget(cases)
    validation = _validation(surface, business=business) if workflow else None
    model = os.environ.get("XCAGI_LLM_MODEL", "").strip()
    endpoint = os.environ.get("XCAGI_LLM_BASE_URL", "").strip()
    if not model or not endpoint.startswith("https://"):
        raise ValueError("training_platform_model_not_configured")
    if surface == "rag_context_prompt" and any(
        case["generation_context"].get("model") != model for case in cases
    ):
        raise ValueError("training_original_model_unbound")
    out_dir.mkdir(parents=True, exist_ok=True)
    # Promptfoo's .md processor preserves bytes. Its .txt processor trims and
    # splits on '---', which changes real prompts and their arm cardinality.
    baseline = out_dir / "baseline_prompt.md"
    candidate = out_dir / "candidate_prompt.md"
    baseline.write_text(_prompt_document(baseline_prompt, surface), encoding="utf-8")
    candidate.write_text(_prompt_document(candidate_prompt, surface), encoding="utf-8")
    tests: list[dict[str, Any]] = [
        {
            "vars": {
                "task": case["task"],
                "case_id": f"case-{index}",
                **({"generation_context": case["generation_context"]} if workflow else {}),
                **(
                    {
                        "evaluation_partition": case["evaluation_partition"],
                        "source_group_sha256": case["source_group_sha256"],
                    }
                    if business
                    else {}
                ),
            },
            "assert": [
                (
                    {
                        "type": "python",
                        "value": f"file://{Path(__file__).with_name(validation[3])}:get_assert",
                    }
                    if validation is not None
                    else {"type": "llm-rubric", "value": _RUBRIC}
                )
            ],
        }
        for index, case in enumerate(cases)
    ]
    tests_path = out_dir / "tests.json"
    tests_path.write_text(json.dumps(tests, ensure_ascii=False), encoding="utf-8")
    provider: dict[str, Any] = {
        "id": f"openai:chat:{model}",
        "config": {
            "apiBaseUrl": endpoint,
            "max_tokens": 4096 if workflow else 1024,
            "maxRetries": 0,
        },
    }
    config = {
        "description": f"{surface} failure regression",
        "prompts": [f"file://{baseline}", f"file://{candidate}"],
        "providers": [provider],
        "defaultTest": {"options": {"provider": provider}},
        "tests": f"file://{tests_path}",
        "sharing": False,
        "writeLatestResults": False,
    }
    config_path = out_dir / "promptfooconfig.yaml"
    # JSON 是 YAML 的子集，promptfoo 可直接读取。
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    files = {
        "config": config_path,
        "baseline": baseline,
        "candidate": candidate,
        "tests": tests_path,
    }
    bundle = {
        "schema": "xcagi.training-bundle/v1",
        "engine": f"promptfoo@{PROMPTFOO_VERSION}",
        "files": {
            name: {"name": path.name, "sha256": _file_hash(path)} for name, path in files.items()
        },
        "prompt_sha256": {
            "control": _hash(baseline_prompt),
            "candidate": _hash(candidate_prompt),
        },
        "provider_id": provider["id"],
        "case_ids": [test["vars"]["case_id"] for test in tests],
        "case_sha256": [_hash(case["task"]) for case in cases],
        "evaluation_scope": "business_regression_and_holdout" if business else "failure_regression",
        "holdout_verified": False,
        **(
            {
                "case_partitions": [case["evaluation_partition"] for case in cases],
                "case_source_groups": [case["source_group_sha256"] for case in cases],
            }
            if business
            else {}
        ),
        **(
            {
                "surface": surface,
                "measurement_scope": validation[0],
                "validation_sha256": validation[1],
                "case_context_sha256": [
                    _hash(
                        json.dumps(
                            case["generation_context"],
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        )
                    )
                    for case in cases
                ],
            }
            if validation is not None
            else {}
        ),
    }
    bundle_path = out_dir / "training-bundle.json"
    bundle_path.write_text(json.dumps(bundle, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    return {
        **{name: str(path) for name, path in files.items()},
        "bundle": str(bundle_path),
    }


def _hash(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def decide(result: dict[str, Any], *, bundle=None) -> dict[str, Any]:
    """Compare the same case/provider pairs; offline success only proposes approval."""
    blocked = {
        "improved": False,
        "verdict": "keep_baseline",
        "evaluation_scope": "failure_regression",
        "holdout_verified": False,
    }
    arms: dict[int, dict[tuple[int, str, str], tuple[bool, dict[str, Any]]]] = {0: {}, 1: {}}
    for row in result.get("results", {}).get("results", []) or []:
        index, test_index = row.get("promptIdx"), row.get("testIdx")
        provider = row.get("provider") or {}
        variables = row.get("vars") or (row.get("testCase") or {}).get("vars") or {}
        if (
            type(index) is not int
            or index not in arms
            or type(test_index) is not int
            or test_index < 0
            or type(row.get("success")) is not bool
            or not isinstance(provider, dict)
            or not provider.get("id")
            or not variables.get("case_id")
            or type(row.get("failureReason")) is not int
            or row["failureReason"] != (0 if row["success"] else 1)
            or (row["success"] and row.get("error"))
            or (not row["success"] and (row.get("gradingResult") or {}).get("pass") is not False)
            or (row.get("response") or {}).get("cached")
        ):
            return {**blocked, "reason": "unpaired_or_invalid_result"}
        key = (test_index, provider["id"], provider.get("label", ""))
        if key in arms[index]:
            return {**blocked, "reason": "duplicate_case_provider_result"}
        arms[index][key] = (row["success"], variables)
    if (
        not arms[0]
        or arms[0].keys() != arms[1].keys()
        or any(arms[0][key][1] != arms[1][key][1] for key in arms[0])
    ):
        return {**blocked, "reason": "case_provider_sets_differ"}
    if (
        bundle is None
        or not isinstance(bundle.get("case_sha256"), list)
        or len(bundle["case_sha256"]) != len(bundle["case_ids"])
        or any(
            key[1] != bundle["provider_id"]
            or key[0] >= len(bundle["case_ids"])
            or value[1]["case_id"] != bundle["case_ids"][key[0]]
            or not isinstance(value[1].get("task"), str)
            or _hash(value[1]["task"]) != bundle["case_sha256"][key[0]]
            for key, value in arms[0].items()
        )
        or {key[0] for key in arms[0]} != set(range(len(bundle["case_ids"])))
    ):
        return {**blocked, "reason": "evaluation_bundle_unbound"}
    baseline, candidate = [
        {"pass": sum(row[0] for row in arms[index].values()), "total": len(arms[index])}
        for index in (0, 1)
    ]
    improved = candidate["pass"] > baseline["pass"] and candidate["pass"] == candidate["total"]
    from modstore_server.workflow_nl_training import offline_execution_feedback

    runtime_candidate = offline_execution_feedback(
        bundle, [value[1] for value in arms[0].values()], candidate["pass"] == candidate["total"]
    )
    return {
        **blocked,
        "baseline": baseline,
        "candidate": candidate,
        "total": len(arms[0]),
        "improved": improved,
        "verdict": "candidate_for_approval" if improved or runtime_candidate else "keep_baseline",
        **runtime_candidate,
    }


def seal_evaluation(bundle_path: Path, result_path: Path):
    """Freeze the exact inputs and official output file before an operator approves a trial."""
    from modstore_server.workflow_training_dataset import (
        bound_result_variables,
        is_business_case,
        seal_business_evidence,
        verify_partitions,
    )

    bundle = json.loads(bundle_path.read_bytes().decode("utf-8"))
    if (
        bundle.get("schema") != "xcagi.training-bundle/v1"
        or bundle.get("engine") != f"promptfoo@{PROMPTFOO_VERSION}"
    ):
        raise ValueError("training_bundle_schema_mismatch")
    surface = bundle.get("surface", "employee_prompt")
    for entry in bundle["files"].values():
        path = bundle_path.parent / entry["name"]
        if (
            path.resolve().parent != bundle_path.parent.resolve()
            or _file_hash(path) != entry["sha256"]
        ):
            raise ValueError("training_input_changed")
    result = json.loads(result_path.read_bytes().decode("utf-8"))
    if (result.get("metadata") or {}).get("promptfooVersion") != PROMPTFOO_VERSION:
        raise ValueError("training_engine_version_unverified")
    prompts = result.get("results", {}).get("prompts") or []
    expected = [
        (bundle_path.parent / bundle["files"][name]["name"]).read_bytes().decode("utf-8")
        for name in ("baseline", "candidate")
    ]
    if bundle.get("prompt_sha256") != {
        key: _hash(_prompt_value(prompt, surface))
        for key, prompt in zip(("control", "candidate"), expected)
    }:
        raise ValueError("training_prompt_hash_mismatch")
    tests = json.loads((bundle_path.parent / bundle["files"]["tests"]["name"]).read_bytes())
    if bundle.get("case_ids") != [test["vars"]["case_id"] for test in tests] or bundle.get(
        "case_sha256"
    ) != [_hash(test["vars"]["task"]) for test in tests]:
        raise ValueError("training_case_hash_mismatch")
    if [prompt.get("raw") for prompt in prompts] != expected:
        raise ValueError("training_result_prompts_unbound")
    business = surface == "workflow_nl_prompt" and any(
        is_business_case(test["vars"]) for test in tests
    )
    verdict = None if business else decide(result, bundle=bundle)
    verified = {}
    if surface in STRUCTURED_SURFACES:
        from modstore_server.workflow_nl_training import _digest

        scope, hashes, get_assert, _module = _validation(surface, business=business)

        if (
            bundle.get("measurement_scope") != scope
            or bundle.get("validation_sha256") != hashes
            or bundle.get("case_context_sha256")
            != [_digest(test["vars"].get("generation_context")) for test in tests]
        ):
            raise ValueError("training_workflow_validation_unbound")
        if business:
            verify_partitions(bundle, [test["vars"] for test in tests])
        pending, pairs = [], set()
        for row in result.get("results", {}).get("results", []):
            variables = row.get("vars") or (row.get("testCase") or {}).get("vars") or {}
            index = row.get("testIdx")
            output = (row.get("response") or {}).get("output")
            if business and type(index) is int and 0 <= index < len(tests):
                variables = bound_result_variables(variables, tests[index]["vars"])
                for container in (row, row.get("testCase") or {}):
                    if "vars" in container:
                        bound_result_variables(container["vars"], tests[index]["vars"])
            if (
                type(index) is not int
                or not 0 <= index < len(tests)
                or variables != tests[index]["vars"]
                or not isinstance(output, str)
            ):
                raise ValueError("training_workflow_result_unverified")
            arm = row.get("promptIdx")
            if business:
                if type(arm) is not int or arm not in (0, 1) or (arm, index) in pairs:
                    raise ValueError("training_business_results_incomplete")
                pairs.add((arm, index))
            pending.append((row, arm, index, output, variables))
        if business and pairs != {(arm, index) for arm in (0, 1) for index in range(len(tests))}:
            raise ValueError("training_business_results_incomplete")
        if business:
            verdict = decide(
                {
                    **result,
                    "results": {
                        **result["results"],
                        "results": [{**row, "vars": values} for row, _, _, _, values in pending],
                    },
                },
                bundle=bundle,
            )
            if "baseline" not in verdict:
                raise ValueError("training_business_results_incomplete")
        # Validate the complete matrix before starting any original native employee.
        measured_rows = []
        for row, arm, index, output, variables in pending:
            from modstore_server.workflow_nl_training import DEFERRED_BUSINESS_REASON

            grading = row.get("gradingResult") or {}
            components = grading.get("componentResults") or [grading]
            deferred = (
                business
                and row.get("success") is False
                and grading.get("pass") is False
                and grading.get("score") == 0
                and isinstance(components, list)
                and len(components) == 1
                and isinstance(components[0], dict)
                and components[0].get("pass") is False
                and components[0].get("score") == 0
                and components[0].get("reason") == DEFERRED_BUSINESS_REASON
            )
            if deferred:
                from modstore_server.workflow_training_replay import evaluate_business_replay

                assertion = evaluate_business_replay(output, variables["generation_context"])
            else:
                assertion = get_assert(output, {"vars": variables})
            if not business and assertion["pass"] is not row.get("success"):
                raise ValueError("training_workflow_result_unverified")
            if business:
                verified[arm, index] = assertion
                passed = assertion["pass"] is True
                measured_rows.append(
                    {
                        **row,
                        "vars": variables,
                        "success": passed,
                        "failureReason": 0 if passed else 1,
                        "error": None if passed else assertion.get("reason"),
                        "gradingResult": assertion,
                    }
                )
        if business:
            # Keep the official output bytes and their hash intact. Only these
            # independently measured rows may supply the business verdict.
            verdict = decide(
                {**result, "results": {**result["results"], "results": measured_rows}},
                bundle=bundle,
            )
    if business:
        verdict = seal_business_evidence(bundle, tests, verified, verdict)
    assert verdict is not None
    return {
        **verdict,
        "engine": bundle["engine"],
        "prompt_sha256": bundle["prompt_sha256"],
        "files": {key: entry["sha256"] for key, entry in bundle["files"].items()},
        "bundle_sha256": _file_hash(bundle_path),
        "results_sha256": _file_hash(result_path),
        **(
            {
                "measurement_scope": bundle["measurement_scope"],
                "validation_sha256": bundle["validation_sha256"],
            }
            if surface in STRUCTURED_SURFACES
            else {}
        ),
    }


def candidate_for_experiment(bundle_path: Path, result_path: Path):
    """Public adapter for an operator template; it grants no execution/rollout permission."""
    evidence = seal_evaluation(bundle_path, result_path)
    if evidence["verdict"] != "candidate_for_approval":
        raise ValueError("training_candidate_not_improved")
    bundle = json.loads(bundle_path.read_bytes().decode("utf-8"))
    prompts = [
        (bundle_path.parent / bundle["files"][name]["name"]).read_bytes().decode("utf-8")
        for name in ("baseline", "candidate")
    ]
    return {
        "control_prompt": _prompt_value(prompts[0], bundle.get("surface", "employee_prompt")),
        "treatment_prompt": _prompt_value(prompts[1], bundle.get("surface", "employee_prompt")),
        "offline_evidence": evidence,
    }


def build_patch_prompt(baseline_prompt: str, clusters: list[dict[str, Any]]) -> str:
    from modstore_server.workflow_training_dataset import proposal_clusters

    clusters = proposal_clusters(clusters)
    reasons = "\n".join(
        f"- {training_identity(cluster)}: {cluster['failure_reason']} ({cluster['count']} 次)"
        + (
            "\n"
            + json.dumps(
                [
                    {
                        "task": sample["task"],
                        "errors": sample.get("validation_errors", []),
                        **(
                            {"context": sample.get("generation_context")}
                            if cluster.get("surface") == "rag_context_prompt"
                            else {
                                "execution": sample.get("generation_context", {}).get(
                                    "execution_feedback"
                                )
                            }
                        ),
                    }
                    for sample in cluster["samples"][:3]
                ],
                ensure_ascii=False,
            )
            if cluster.get("surface") in STRUCTURED_SURFACES
            else ""
        )
        for cluster in clusters
    )
    return (
        "你是员工能力训练器。下面是该员工当前的 system prompt 与最近的真实失败原因。\n"
        "只做最小必要修改，让失败原因不再发生；不要新增工具、不要改变输出协议、"
        "不要声称任何未经回执验证的完成。只归纳通用规则，不复制客户原输入。"
        "只输出修改后的完整 prompt 正文。\n\n"
        f"=== 当前 prompt ===\n{baseline_prompt}\n\n=== 真实失败 ===\n{reasons}\n"
    )


def suggest_prompt(baseline_prompt: str, clusters: list[dict[str, Any]]) -> str:
    from modstore_server.employee_pack_proposal import _call_llm

    raw = _call_llm(build_patch_prompt(baseline_prompt, clusters))
    text = ""
    if isinstance(raw, dict):
        text = str(raw.get("text") or raw.get("content") or "")
        if not text and isinstance(raw.get("choices"), list) and raw["choices"]:
            text = str((raw["choices"][0].get("message") or {}).get("content") or "")
    text = text.strip()
    return text or baseline_prompt


def _default_ledger() -> Path:
    try:
        from modstore_server.maintenance_loop.store import ledger_path

        return ledger_path()
    except (OSError, ValueError, ImportError):
        return (
            Path(os.environ.get("MODSTORE_TRAINING_LEDGER_PATH", ""))
            if os.environ.get("MODSTORE_TRAINING_LEDGER_PATH")
            else Path("self_maintenance_loop_runs.jsonl")
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    mine_p = sub.add_parser("mine", help="统计失败簇，不输出原始样本")
    mine_p.add_argument("--ledger", default="")
    mine_p.add_argument("--days", type=int, default=DEFAULT_DAYS)
    mine_p.add_argument("--min-count", type=int, default=DEFAULT_MIN_COUNT)

    select = sub.add_parser("select", help="选择具备独立业务留出样本的原失败簇")
    select.add_argument("--clusters", required=True)
    select.add_argument("--out", required=True)

    prep = sub.add_parser("prepare", help="生成回归集与 promptfoo 配置")
    prep.add_argument("--clusters", required=True)
    prep.add_argument("--packs-dir", required=True)
    prep.add_argument("--corpus-dir", required=True)
    prep.add_argument("--out-dir", required=True)
    prep.add_argument("--employee-id", required=True)
    prep.add_argument("--candidate-prompt", required=True)
    prep.add_argument(
        "--surface",
        choices=("employee_prompt", *sorted(STRUCTURED_SURFACES)),
        default="employee_prompt",
    )
    prep.add_argument("--baseline", default="")

    baseline_parser = sub.add_parser("baseline", help="从固定执行面的源码读取当前提示词")
    baseline_parser.add_argument(
        "--surface", choices=("employee_prompt", *sorted(STRUCTURED_SURFACES)), required=True
    )
    baseline_parser.add_argument("--source", required=True)
    baseline_parser.add_argument("--out", required=True)

    dec = sub.add_parser("decide", help="判定候选是否晋级")
    dec.add_argument("--result", required=True)
    dec.add_argument("--bundle", required=True)

    sug = sub.add_parser("suggest", help="用 LLM 生成 prompt 候选")
    sug.add_argument("--baseline", required=True)
    sug.add_argument("--clusters", required=True)
    sug.add_argument("--out", required=True)

    args = parser.parse_args(argv)
    if args.command == "select":
        from modstore_server.workflow_training_dataset import select_clusters

        payload = json.loads(Path(args.clusters).read_bytes())
        clusters, blocked = select_clusters(payload["clusters"])
        Path(args.out).write_text(json.dumps(clusters, ensure_ascii=False), encoding="utf-8")
        print(json.dumps({"clusters": len(clusters), "blocked": blocked}, ensure_ascii=False))
        return 0
    if args.command == "baseline":
        text = prompt_from_source(
            Path(args.source).read_bytes().decode("utf-8"), surface=args.surface
        )
        Path(args.out).write_text(text, encoding="utf-8")
        return 0
    if args.command == "mine":
        ledger = Path(args.ledger) if args.ledger else _default_ledger()
        clusters = mine(ledger, days=args.days, min_count=args.min_count)
        print(
            json.dumps(
                {
                    "cluster_count": len(clusters),
                    "failure_count": sum(cluster["count"] for cluster in clusters),
                    "sample_count": sum(len(cluster["samples"]) for cluster in clusters),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    if args.command == "prepare":
        clusters = json.loads(Path(args.clusters).read_bytes().decode("utf-8"))
        if not isinstance(clusters, list):
            raise SystemExit("clusters 必须是数组")
        clusters = [
            cluster
            for cluster in clusters
            if training_identity(cluster) == (args.surface, args.employee_id)
        ]
        cases = append_cases(Path(args.corpus_dir), clusters)
        pack = (
            select_pack(Path(args.packs_dir), args.employee_id)
            if args.surface == "employee_prompt"
            else None
        )
        if args.surface == "employee_prompt" and pack is None:
            print(json.dumps({"ok": False, "reason": "pack_prompt_not_found"}))
            return 0
        key = (
            args.employee_id
            if args.surface == "employee_prompt"
            else f"{args.surface}-{args.employee_id}"
        )
        corpus_path = Path(args.corpus_dir) / f"{key}.jsonl"
        persisted = load_cases(corpus_path)
        from modstore_server.workflow_training_dataset import is_business_case

        if any(is_business_case(sample) for cluster in clusters for sample in cluster["samples"]):
            current_sources = {
                (str(sample["run_id"]), _case_id(cluster, sample))
                for cluster in clusters
                for sample in cluster["samples"]
                if sample.get("run_id")
            }
            persisted = [
                case
                for case in persisted
                if (case.get("source_run"), case.get("case_id")) in current_sources
            ]
        if not persisted:
            print(json.dumps({"ok": False, "reason": "training_reproduction_cases_required"}))
            return 0
        built = build_config(
            out_dir=Path(args.out_dir),
            baseline_prompt=(pack / "prompt.txt" if pack else Path(args.baseline))
            .read_bytes()
            .decode("utf-8"),
            candidate_prompt=Path(args.candidate_prompt).read_bytes().decode("utf-8"),
            cases=persisted[-20:],
            surface=args.surface,
        )
        print(json.dumps({"ok": True, "cases": len(cases), **built}, ensure_ascii=False))
        return 0
    if args.command == "suggest":
        clusters = json.loads(Path(args.clusters).read_bytes().decode("utf-8"))
        baseline = Path(args.baseline).read_bytes().decode("utf-8")
        Path(args.out).write_text(suggest_prompt(baseline, clusters), encoding="utf-8")
        print(json.dumps({"ok": True, "out": args.out}))
        return 0
    print(json.dumps(seal_evaluation(Path(args.bundle), Path(args.result)), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
