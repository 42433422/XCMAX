"""WG11 rules for the existing independent operating gate; never a task runtime.

Inputs are independently collected original records, not generated test results.
The audit signer must verify their authoritative origins before signing. Hashes
and this parser prove consistency, not the physical truth of an invented record.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from graphlib import CycleError, TopologicalSorter
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.dev.autonomy_operating_gate import (
    STABILITY_CHECKS,
    _continuity,
    _digest,
    _json,
    _read_regular,
    _rows,
    _stamp,
    stability_report,
)

COHORTS = {"basic": (100, 99), "complex": (100, 95), "recovery": (100, 99), "handoff": (1000, 100)}
RECOVERABLE = {"process_crash", "network_loss", "timeout", "late_receipt", "duplicate_receipt"}
KINDS = {"protocol", "execution", "verification", "continuity", "service", "platforms"}
IDENTITY = ("source_sha", "environment", "release_artifact_sha256", "deployment_receipt_sha256")
STAGES = {"signature", "installation", "download", "business", "upgrade", "rollback"}


def _strings(value: object, name: str, *, empty: bool = False) -> set[str]:
    if (
        not isinstance(value, list)
        or (not value and not empty)
        or any(not isinstance(x, str) or not x.strip() for x in value)
        or len(value) != len(set(value))
    ):
        raise ValueError(f"{name}: missing, malformed or duplicate identities")
    return set(value)


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name}: missing identity")
    return value


def _index(rows: list[dict], key: str) -> dict[str, dict]:
    _strings([row.get(key) for row in rows], key)
    return {row[key]: row for row in rows}


def _reason(exc: Exception) -> str:
    return "original evidence file unavailable" if isinstance(exc, OSError) else str(exc)


class Bundle:
    """Read only exact, contained, non-symlinked files covered by the audit MAC."""

    def __init__(self, root: Path, payload: dict, provenance: dict, now: datetime):
        self.root, self.payload, self.provenance, self.now = root, payload, provenance, now
        self.contents: dict[Path, bytes] = {}

    def path(self, name: object) -> Path:
        if (
            not isinstance(name, str)
            or not name
            or "\\" in name
            or Path(name).is_absolute()
            or any(p in {"", ".", ".."} for p in name.split("/"))
        ):
            raise ValueError("unsafe evidence path")
        path = self.root
        if path.is_symlink():
            raise ValueError("symlinked evidence root")
        for part in name.split("/"):
            path /= part
            if path.is_symlink():
                raise ValueError("symlinked evidence path")
        if not path.resolve().is_relative_to(self.root.resolve()):
            raise ValueError("evidence path escapes root")
        return path

    def raw(self, reference: object) -> dict:
        if (
            not isinstance(reference, dict)
            or set(reference) != {"path", "sha256"}
            or not _digest(reference["sha256"])
        ):
            raise ValueError("missing raw receipt reference")
        path = self.path(reference["path"])
        if path not in self.contents:
            if not path.is_file() or path.stat().st_size > 16_000_000:
                raise ValueError("raw receipt missing or oversized")
            self.contents[path] = _read_regular(path, 16_000_000)
        raw = self.contents[path]
        if hashlib.sha256(raw).hexdigest() != reference["sha256"]:
            raise ValueError("raw receipt checksum mismatch")
        return _json(raw)

    def record(self, reference: object, kind: str) -> dict:
        data = self.raw(reference)
        if any(data.get(k) != self.payload[k] for k in IDENTITY) or data.get("record_type") != kind:
            raise ValueError(f"{kind}: raw receipt source/release/deployment/type mismatch")
        producer = _text(data.get("producer_id"), "producer_id")
        if (kind == "execution" and producer == self.provenance["auditor_id"]) or (
            kind != "execution" and producer != self.provenance["auditor_id"]
        ):
            raise ValueError(f"{kind}: execution and independent verifier are not separate")
        if _stamp(data.get("captured_at")) > min(self.now, _stamp(self.provenance["captured_at"])):
            raise ValueError(
                f"{kind}: receipt captured after the audit manifest or verification time"
            )
        return data


def _campaign(data: dict[str, dict], now: datetime) -> list[tuple[dict, dict, dict]]:
    protocol, execution, verification = (data[k] for k in ("protocol", "execution", "verification"))
    frozen = _stamp(protocol.get("frozen_at"))
    registered = _stamp(protocol.get("captured_at"))
    if frozen > registered:
        raise ValueError("frozen protocol timestamp precedes original registration")
    planned = _index(_rows(protocol, "rounds"), "run_id")
    executed = _index(_rows(execution, "rounds"), "run_id")
    verified = _index(_rows(verification, "rounds"), "run_id")
    if planned.keys() != executed.keys() or planned.keys() != verified.keys():
        raise ValueError("frozen round inventory differs: missing, added or dropped trials")
    _strings([r.get("receipt_id") for r in executed.values()], "execution receipt")
    _strings([r.get("receipt_id") for r in verified.values()], "verification receipt")
    if {r["receipt_id"] for r in executed.values()} & {r["receipt_id"] for r in verified.values()}:
        raise ValueError("execution receipt reused as independent verification")
    result = []
    event_ids: dict[str, set[str]] = {
        key: set()
        for key in (
            "model_request_ids",
            "tool_call_ids",
            "child_task_id",
            "dispatch_id",
            "child_receipt_id",
        )
    }
    for run_id, plan in planned.items():
        actual, check = executed[run_id], verified[run_id]
        if plan.get("cohort") not in COHORTS or not _digest(plan.get("goal_sha256")):
            raise ValueError("round lacks frozen cohort/goal")
        _text(plan.get("task_id"), "task_id")
        if any(
            row.get(k) != plan[k] for row in (actual, check) for k in ("task_id", "goal_sha256")
        ):
            raise ValueError("round task identity or frozen goal changed")
        if (
            not registered
            <= _stamp(actual.get("started_at"))
            <= _stamp(actual.get("finished_at"))
            <= _stamp(check.get("verified_at"))
            <= now
        ):
            raise ValueError("round outside preregistered actual execution window")
        if _stamp(actual["finished_at"]) > _stamp(execution["captured_at"]) or _stamp(
            check["verified_at"]
        ) > _stamp(verification["captured_at"]):
            raise ValueError("snapshot contains a result later than its capture time")
        for key, seen in event_ids.items():
            if key.endswith("_ids"):
                ids = _strings(actual.get(key, []), key, empty=True)
            elif plan["cohort"] == "handoff":
                ids = {_text(actual.get(key), key)}
            else:
                continue
            if ids & seen:
                raise ValueError(f"{key}: event reused across frozen rounds")
            seen.update(ids)
        if type(actual.get("claimed_complete")) is not bool or check.get("status") not in {
            "PASS",
            "FAIL",
            "BLOCKED",
            "UNKNOWN",
        }:
            raise ValueError("invalid completion claim or independent outcome")
        if (
            check.get("completion_verified") is not None
            and type(check["completion_verified"]) is not bool
        ):
            raise ValueError("completion verification must be a boolean or unknown")
        _strings(actual.get("operation_ids"), "business operation", empty=True)
        result.append((plan, actual, check))
    return result


def _trials(rounds: list[tuple[dict, dict, dict]], cohort: str, metrics: dict) -> None:
    selected = [(p, a, v) for p, a, v in rounds if p["cohort"] == cohort]
    minimum, percent = COHORTS[cohort]
    passed = sum(v["status"] == "PASS" for _, _, v in selected)
    metrics.update(
        planned=len(selected), successful=passed, minimum_rounds=minimum, minimum_percent=percent
    )
    if len(selected) < minimum:
        raise ValueError(f"{cohort}: {len(selected)}/{minimum} frozen rounds")
    request_ids, handoff_ids, fault_types = set(), set(), set()
    for plan, actual, check in selected:
        if cohort in {"basic", "complex"}:
            if actual.get("execution_mode") != "real_model":
                raise ValueError("requires real model execution, not mock/rule fallback")
            _text(actual.get("model_id"), "model_id")
            requests = _strings(actual.get("model_request_ids"), "actual model request")
            responses = actual.get("model_responses")
            if type(responses) is not int or not 0 <= responses <= len(requests):
                raise ValueError("invalid actual model response count")
            if check["status"] == "PASS" and responses == 0:
                raise ValueError("successful trial has no actual model response")
            if request_ids & requests:
                raise ValueError("model request reused across rounds")
            request_ids.update(requests)
            steps = _strings(
                actual.get("step_ids"), "runtime steps", empty=check["status"] != "PASS"
            )
            _strings(
                actual.get("tool_call_ids"), "actual tool calls", empty=check["status"] != "PASS"
            )
            if cohort == "complex" and check["status"] == "PASS":
                edges = actual.get("dependencies")
                if (
                    len(steps) < 2
                    or not isinstance(edges, list)
                    or not edges
                    or any(
                        not isinstance(edge, list)
                        or len(edge) != 2
                        or any(x not in steps for x in edge)
                        or edge[0] == edge[1]
                        for edge in edges
                    )
                ):
                    raise ValueError("complex task lacks executed step dependencies")
                graph = {step: set() for step in steps}
                for before, after in edges:
                    graph[after].add(before)
                try:
                    tuple(TopologicalSorter(graph).static_order())
                except CycleError as exc:
                    raise ValueError("complex task contains a dependency cycle") from exc
            if check["status"] == "PASS" and check.get("completion_verified") is not True:
                raise ValueError("successful task lacks independent goal verification")
        elif cohort == "recovery":
            fault = actual.get("fault_type")
            if actual.get("execution_mode") != "production_runtime" or fault not in RECOVERABLE:
                raise ValueError("requires an actual recoverable production runtime fault")
            fault_types.add(fault)
            if (
                not _stamp(actual["started_at"])
                <= _stamp(actual.get("injected_at"))
                <= _stamp(actual["finished_at"])
            ):
                raise ValueError("fault injection outside round")
            if check["status"] == "PASS" and (
                check.get("recovered") is not True
                or not _stamp(actual["injected_at"])
                <= _stamp(check.get("recovered_at"))
                <= _stamp(check["verified_at"])
            ):
                raise ValueError("successful recovery lacks independent timed recovery")
        else:
            if actual.get("execution_mode") != "production_runtime":
                raise ValueError("handoff was not executed by the production runtime")
            child = _text(actual.get("child_task_id"), "child_task_id")
            if (
                child == plan["task_id"]
                or actual.get("continued_parent_task_id") != plan["task_id"]
            ):
                raise ValueError("handoff changed original parent/child identity")
            for field in ("dispatch_id", "child_receipt_id"):
                identity = _text(actual.get(field), field)
                if identity in handoff_ids:
                    raise ValueError("replayed handoff dispatch or receipt")
                handoff_ids.add(identity)
            if not (
                _stamp(actual["started_at"])
                <= _stamp(actual.get("waiting_at"))
                <= _stamp(actual.get("child_terminal_at"))
                <= _stamp(actual.get("parent_resumed_at"))
                <= _stamp(actual["finished_at"])
            ):
                raise ValueError(
                    "handoff does not prove waiting, child receipt and parent continuation"
                )
            if check.get("false_lock") is not False or check.get("parent_continued") is not True:
                raise ValueError("handoff false lock or unverified parent continuation")
    if cohort == "recovery" and fault_types != RECOVERABLE:
        raise ValueError("recoverable fault matrix incomplete")
    if 100 * passed < percent * len(selected):
        raise ValueError(f"{cohort}: {passed}/{len(selected)} below {percent}%")


def _effects(rounds: list[tuple[dict, dict, dict]], metrics: dict) -> None:
    operations, effects = set(), set()
    for _, actual, check in rounds:
        expected = _strings(actual["operation_ids"], "business operation", empty=True)
        rows = check.get("effects")
        if not isinstance(rows, list) or any(not isinstance(x, dict) for x in rows):
            raise ValueError("missing independently queried effects")
        observed = {r.get("operation_id") for r in rows}
        if observed != expected or len(observed) != len(rows) or operations & observed:
            raise ValueError("business intent coverage missing, duplicate or ambiguous")
        operations.update(observed)
        for effect in rows:
            desired = _strings(
                effect.get("expected_effect_ids"), "authorized expected effects", empty=True
            )
            found = _strings(effect.get("actual_effect_ids"), "actual effects", empty=True)
            if desired != found or effects & found:
                raise ValueError("duplicate, missing or unauthorized business effect")
            effects.update(found)
    metrics.update(audited_operations=len(operations), unique_effects=len(effects))
    if not operations or not effects:
        raise ValueError("no actual business effects independently reconciled")


def _completion(rounds: list[tuple[dict, dict, dict]], metrics: dict) -> None:
    claims = sum(actual["claimed_complete"] for _, actual, _ in rounds)
    metrics.update(audited_rounds=len(rounds), completion_claims=claims)
    for _, actual, check in rounds:
        if check.get("completion_verified") is None or check["status"] == "UNKNOWN":
            raise ValueError("unknown verification cannot prove zero false completion")
        if actual["claimed_complete"] and (
            check["status"] != "PASS" or check.get("completion_verified") is not True
        ):
            raise ValueError("completion claimed without independent completion")
    if not claims:
        raise ValueError("no completion claims independently checked")


def _soak(data: dict, seconds: int, now: datetime, metrics: dict) -> None:
    _continuity(data, seconds, now)
    samples = _rows(data, "samples")
    captured = _stamp(data["captured_at"])
    tasks = _index(_rows(data, "tasks"), "task_id")
    if _strings(data.get("accepted_task_ids"), "accepted SQL task ledger") != tasks.keys():
        raise ValueError("accepted task ledger differs from independently reconciled tasks")
    _strings([task.get("ledger_receipt_id") for task in tasks.values()], "task ledger receipt")
    previous = -1
    for sample in samples:
        progress = sample.get("workload_revision")
        if (
            type(sample.get("seq")) is not int
            or _stamp(sample.get("at")) > captured
            or sample.get("task_id") not in tasks
            or type(progress) is not int
            or progress <= previous
        ):
            raise ValueError("heartbeat lacks advancing Agent workload evidence")
        previous = progress
    for task in tasks.values():
        if not _stamp(task.get("accepted_at")) <= _stamp(task.get("updated_at")) <= captured:
            raise ValueError("task ledger event occurs after the continuity snapshot")
        if (
            task.get("status") not in {"completed", "failed", "cancelled", "waiting"}
            or task.get("independently_reconciled") is not True
        ):
            raise ValueError("lost or unreconciled task in continuous workload")
        if (
            type(task.get("duplicate_effects")) is not int
            or task["duplicate_effects"] != 0
            or task.get("unrecoverable_stuck") is not False
        ):
            raise ValueError("duplicate effects or unrecoverable stuck task")
        if task["status"] == "completed" and task.get("completion_verified") is not True:
            raise ValueError("continuous workload contains false completion")
        if task["status"] == "waiting" and (
            task.get("waiting_reason") not in {"approval", "dependency", "scheduled"}
            or not task.get("waiting_receipt_id")
        ):
            raise ValueError("unproven legitimate waiting task")
    start, end = _stamp(samples[0]["at"]), _stamp(samples[-1]["at"])
    for sample in samples:
        task = tasks[sample["task_id"]]
        if not _stamp(task["accepted_at"]) <= _stamp(sample["at"]) <= _stamp(task["updated_at"]):
            raise ValueError("workload sample outside its task ledger lifetime")
    metrics.update(
        samples=len(samples),
        accepted_tasks=len(tasks),
        observed_seconds=(end - start).total_seconds(),
    )
    if seconds >= 72 * 3600:
        faults = _rows(data, "faults")
        if {fault.get("type") for fault in faults} != RECOVERABLE:
            raise ValueError("72h actual recoverable fault matrix incomplete")
        _strings([fault.get("receipt_id") for fault in faults], "soak fault receipt")
        for fault in faults:
            if (
                fault.get("task_id") not in tasks
                or fault.get("recovered") is not True
                or not start
                <= _stamp(fault.get("injected_at"))
                <= _stamp(fault.get("recovered_at"))
                <= end
            ):
                raise ValueError("72h fault recovery outside observation or task ledger")


def _service(bundle: Bundle, data: dict, metrics: dict) -> None:
    from scripts.observability.verify_production_slo_window import verify_window

    directory = bundle.path(data.get("evidence_dir"))
    files = _rows(data, "files")
    _strings([item.get("path") for item in files], "SLO file inventory")
    if not directory.is_dir() or {bundle.path(item["path"]) for item in files} != set(
        directory.glob("*.json")
    ):
        raise ValueError("SLO raw chain inventory differs from independently signed inventory")
    version = _text(data.get("release_version"), "release_version")
    if data.get("release_id") != f"xcagi-{version}-{bundle.payload['source_sha']}":
        raise ValueError("SLO release identity does not bind the exact source SHA")
    with TemporaryDirectory(prefix="xcagi-stability-slo-") as scratch:
        snapshot = Path(scratch)
        for item in files:
            bundle.raw(item)
            source = bundle.path(item["path"])
            (snapshot / source.name).write_bytes(bundle.contents[source])
        result = verify_window(
            snapshot, release_id=data["release_id"], required_days=30, now=bundle.now
        )
    metrics.update({k: result[k] for k in ("continuous_days", "continuous_seconds", "window")})
    if result.get("passed") is not True:
        metrics["blocker_count"] = len(result["blockers"])
        raise ValueError(
            "30d original SLO verification failed; inspect the protected raw SLO records"
        )


def _platforms(bundle: Bundle, data: dict, metrics: dict) -> None:
    devices = _rows(data, "devices")
    if {device.get("platform") for device in devices} != {"windows", "macos", "android", "ios"}:
        raise ValueError("four-platform physical delivery matrix incomplete")
    _strings([device.get("device_id") for device in devices], "physical device")
    used_receipts = set()
    for device in devices:
        package = device.get("package_sha256")
        if (
            device.get("physical") is not True
            or device.get("emulator") is not False
            or device.get("signing") != "signed"
            or not _digest(package)
            or any(
                device.get(k) != package
                for k in ("installed_artifact_sha256", "downloaded_artifact_sha256")
            )
            or any(
                device.get(k) != bundle.payload["source_sha"]
                for k in ("build_info_sha", "backend_sha", "ui_sha")
            )
        ):
            raise ValueError(
                "device is emulated, unsigned or not the exact installed source/artifact"
            )
        receipts = device.get("receipts")
        if not isinstance(receipts, dict) or set(receipts) != STAGES:
            raise ValueError(
                "device lacks signature/install/download/business/upgrade/rollback originals"
            )
        for stage, reference in receipts.items():
            record = bundle.record(reference, "platform_stage")
            receipt_id = _text(record.get("receipt_id"), "platform receipt")
            if (
                receipt_id in used_receipts
                or record.get("stage") != stage
                or record.get("platform") != device["platform"]
                or record.get("device_id") != device["device_id"]
                or record.get("package_sha256") != package
                or record.get("status") != "PASS"
            ):
                raise ValueError(
                    "device receipt is duplicated, failed or belongs to another stage/device/artifact"
                )
            used_receipts.add(receipt_id)
    metrics.update(physical_devices=len(devices), verified_stages=len(used_receipts))


def evaluate_stability(
    root: Path, source_sha: str, payload: dict | None, provenance: dict, now: datetime
) -> dict:
    checks, blockers, metrics = dict.fromkeys(STABILITY_CHECKS, "BLOCKED"), {}, {}
    try:
        if not isinstance(payload, dict):
            raise ValueError("missing independently signed stability artifact")
        references = payload.get("records")
        if (
            not isinstance(references, dict)
            or not references
            or not set(references).issubset(KINDS)
        ):
            raise ValueError("stability raw record inventory missing or unknown")
        bundle = Bundle(root, payload, provenance, now)
        data = {kind: bundle.record(reference, kind) for kind, reference in references.items()}
        # Integrity failures in nested originals invalidate the submitted bundle,
        # even when the associated K09/K10 functional gate has not yet passed.
        if "service" in data:
            for item in _rows(data["service"], "files"):
                bundle.raw(item)
        if "platforms" in data:
            for device in _rows(data["platforms"], "devices"):
                receipts = device.get("receipts", {})
                if not isinstance(receipts, dict):
                    raise ValueError("malformed platform receipt inventory")
                for reference in receipts.values():
                    bundle.record(reference, "platform_stage")
    except (OSError, ValueError, KeyError, TypeError, OverflowError) as exc:
        return stability_report(
            source_sha,
            checks,
            dict.fromkeys(STABILITY_CHECKS, f"raw evidence: {_reason(exc)}"),
            metrics,
            provenance,
        )
    try:
        rounds = _campaign(data, now)
        for gate, cohort in zip(STABILITY_CHECKS[:4], COHORTS):
            metrics[gate] = {}
            try:
                _trials(rounds, cohort, metrics[gate])
                checks[gate] = "PASS"
            except (ValueError, KeyError, TypeError, OverflowError) as exc:
                blockers[gate] = str(exc)
        for gate, validator in (("K05", _effects), ("K06", _completion)):
            metrics[gate] = {}
            try:
                validator(rounds, metrics[gate])
                checks[gate] = "PASS"
            except (ValueError, KeyError, TypeError, OverflowError) as exc:
                blockers[gate] = str(exc)
    except (ValueError, KeyError, TypeError, OverflowError) as exc:
        blockers.update(dict.fromkeys(STABILITY_CHECKS[:6], f"campaign evidence: {exc}"))
    validators = {
        "K07": lambda m: _soak(data["continuity"], 8 * 3600, now, m),
        "K08": lambda m: _soak(data["continuity"], 72 * 3600, now, m),
        "K09": lambda m: _service(bundle, data["service"], m),
        "K10": lambda m: _platforms(bundle, data["platforms"], m),
    }
    for gate, validator in validators.items():
        metrics[gate] = {}
        try:
            validator(metrics[gate])
            checks[gate] = "PASS"
        except (OSError, ValueError, KeyError, TypeError, OverflowError) as exc:
            blockers[gate] = _reason(exc)
    return stability_report(source_sha, checks, blockers, metrics, provenance)
