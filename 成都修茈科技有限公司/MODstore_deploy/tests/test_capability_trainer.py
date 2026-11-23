import json
import os
import sys
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet

from modstore_server import capability_trainer as trainer


@pytest.fixture
def corpus_key(monkeypatch):
    monkeypatch.setenv("MODSTORE_LLM_MASTER_KEY", Fernet.generate_key().decode("ascii"))


def _rec(employee="daily-orchestrator", reason="marker_missing", status="failed", ts=None):
    return {
        "employee_id": employee,
        "error": reason,
        "status": status,
        "step": "review",
        "report_excerpt": "任务正文",
        "timestamp": ts or datetime.now(timezone.utc).isoformat(),
        "run_id": "r1",
    }


def test_cluster_requires_min_count_and_summarizes():
    records = [_rec(), _rec(), _rec(), _rec(employee="other", reason="x")]
    clusters = trainer.cluster_failures(records, min_count=2)
    assert len(clusters) == 1
    assert clusters[0]["employee_id"] == "daily-orchestrator"
    assert clusters[0]["count"] == 3


def test_cluster_ignores_old_and_successful_records():
    old = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    records = [_rec(ts=old), _rec(ts=old), _rec(status="success")]
    assert trainer.cluster_failures(records, min_count=1) == []


def test_append_cases_is_idempotent(tmp_path, corpus_key):
    clusters = trainer.cluster_failures([_rec(), _rec()], min_count=1)
    first = trainer.append_cases(tmp_path, clusters)
    second = trainer.append_cases(tmp_path, clusters)
    assert len(first) == 1
    assert second == []
    path = tmp_path / "daily-orchestrator.jsonl"
    encrypted = path.read_text(encoding="utf-8")
    assert set(json.loads(encrypted)) == {"schema", "ciphertext"}
    assert "daily-orchestrator" not in encrypted and "任务正文" not in encrypted
    assert path.stat().st_mode & 0o777 == 0o600
    persisted = trainer.load_cases(path)[0]
    assert "employee_id" not in persisted
    assert persisted["resource_id"] == "daily-orchestrator"
    assert persisted["surface"] == "employee_prompt"
    assert persisted["task"] == "任务正文"
    assert persisted["case_id"] == first[0]["case_id"] == "292ff0293853d560"
    assert trainer.load_cases(path) == first
    assert path.read_text(encoding="utf-8") == encrypted
    # Legacy records are encrypted without changing their identity, input or hash.
    legacy = {**persisted, "employee_id": "daily-orchestrator"}
    legacy.pop("surface")
    path.write_text(json.dumps(legacy) + "\n", encoding="utf-8")
    assert trainer.append_cases(tmp_path, clusters) == []
    assert trainer.load_cases(path) == [legacy]
    assert "daily-orchestrator" not in path.read_text(encoding="utf-8")


def test_workflow_corpus_preserves_private_reproduction_input(tmp_path, corpus_key):
    cluster = {
        "surface": "workflow_nl_prompt",
        "resource_id": "workflow_nl_generator",
        "failure_reason": "private-reason-sentinel",
        "samples": [
            {
                "task": "private-task-sentinel\r\n原输入\n",
                "run_id": "private-run-sentinel",
                "generation_context": {
                    "user_id": 7,
                    "input": "private-context-sentinel",
                    "target_employee_pack_id": "worker@1.0",
                    "execution_feedback": {"status": "failed"},
                },
            }
        ],
    }
    original = deepcopy(cluster)
    written = trainer.append_cases(tmp_path, [cluster])
    path = tmp_path / "workflow_nl_prompt-workflow_nl_generator.jsonl"
    assert "private-" not in path.read_text(encoding="utf-8")
    assert trainer.load_cases(path) == written
    assert written[0]["case_id"] == trainer._case_id(cluster, cluster["samples"][0])
    assert written[0]["surface"] == "workflow_nl_prompt"
    assert written[0]["resource_id"] == "workflow_nl_generator"
    assert "employee_id" not in written[0]
    assert written[0]["source_run"] == "private-run-sentinel"
    assert written[0]["task"] == cluster["samples"][0]["task"]
    assert written[0]["generation_context"] == cluster["samples"][0]["generation_context"]
    assert cluster == original
    assert trainer.training_identity(cluster) == ("workflow_nl_prompt", "workflow_nl_generator")
    assert trainer.append_cases(tmp_path, [cluster]) == []
    changed = deepcopy(cluster)
    changed["samples"][0]["generation_context"]["target_employee_pack_id"] = "other-worker@1.0"
    added = trainer.append_cases(tmp_path, [changed])
    assert added[0]["case_id"] != written[0]["case_id"]
    assert trainer.load_cases(path) == written + added
    assert "private-" not in path.read_text(encoding="utf-8")


def test_corpus_missing_key_preserves_legacy_input_and_refuses_new_plaintext(tmp_path, monkeypatch):
    monkeypatch.delenv("MODSTORE_LLM_MASTER_KEY", raising=False)
    clusters = trainer.cluster_failures([_rec()], min_count=1)
    path = tmp_path / "daily-orchestrator.jsonl"
    with pytest.raises(RuntimeError, match="MODSTORE_LLM_MASTER_KEY not configured"):
        trainer.append_cases(tmp_path, clusters)
    assert not path.exists()
    legacy = json.dumps({"case_id": "original-id", "task": "private-task-sentinel"}) + "\n"
    path.write_text(legacy, encoding="utf-8")
    with pytest.raises(RuntimeError, match="MODSTORE_LLM_MASTER_KEY not configured"):
        trainer.load_cases(path)
    assert path.read_text(encoding="utf-8") == legacy
    assert not list(tmp_path.glob(".training-corpus-*"))


@pytest.mark.parametrize("damage", ["wrong_key", "ciphertext", "schema", "invalid_record"])
def test_corpus_cannot_discard_unreadable_existing_samples(
    tmp_path, monkeypatch, corpus_key, damage
):
    clusters = trainer.cluster_failures([_rec()], min_count=1)
    trainer.append_cases(tmp_path, clusters)
    path = tmp_path / "daily-orchestrator.jsonl"
    if damage == "wrong_key":
        monkeypatch.setenv("MODSTORE_LLM_MASTER_KEY", Fernet.generate_key().decode("ascii"))
    else:
        record = json.loads(path.read_text(encoding="utf-8"))
        if damage == "invalid_record":
            path.write_text(path.read_text(encoding="utf-8") + "not-json\n", encoding="utf-8")
        else:
            record[damage] = "damaged"
            path.write_text(json.dumps(record) + "\n", encoding="utf-8")
    original = path.read_bytes()
    clusters[0]["samples"][0]["task"] = "another-private-task"
    with pytest.raises(ValueError):
        trainer.append_cases(tmp_path, clusters)
    assert path.read_bytes() == original
    assert not list(tmp_path.glob(".training-corpus-*"))


def test_corpus_atomic_replace_failure_preserves_old_samples(tmp_path, monkeypatch, corpus_key):
    clusters = trainer.cluster_failures([_rec()], min_count=1)
    trainer.append_cases(tmp_path, clusters)
    path = tmp_path / "daily-orchestrator.jsonl"
    original = path.read_bytes()

    def unavailable(*_args):
        raise OSError("fixture write failure")

    monkeypatch.setattr(trainer.os, "replace", unavailable)
    clusters[0]["samples"][0]["task"] = "new-private-task"
    with pytest.raises(OSError, match="fixture write failure"):
        trainer.append_cases(tmp_path, clusters)
    assert path.read_bytes() == original
    assert not list(tmp_path.glob(".training-corpus-*"))


@pytest.mark.parametrize("filename", ["daily-orchestrator.jsonl", ".capability-corpus.lock"])
def test_corpus_rejects_symbolic_links_without_touching_target(tmp_path, corpus_key, filename):
    outside = tmp_path / "outside"
    outside.write_text("private external file", encoding="utf-8")
    outside.chmod(0o644)
    (tmp_path / filename).symlink_to(outside)
    clusters = trainer.cluster_failures([_rec()], min_count=1)
    with pytest.raises(ValueError, match="cannot be a symbolic link"):
        trainer.append_cases(tmp_path, clusters)
    assert outside.read_text(encoding="utf-8") == "private external file"
    assert outside.stat().st_mode & 0o777 == 0o644


@pytest.mark.skipif(not hasattr(os, "O_NOFOLLOW"), reason="requires no-follow file descriptors")
@pytest.mark.parametrize("filename", ["daily-orchestrator.jsonl", ".capability-corpus.lock"])
def test_corpus_rejects_symbolic_link_swap_before_open(tmp_path, monkeypatch, corpus_key, filename):
    outside = tmp_path / "outside"
    outside.write_text("private external file", encoding="utf-8")
    outside.chmod(0o644)
    target = tmp_path / filename
    original_open = os.open

    def swapped_open(path, flags, *args, **kwargs):
        if Path(path) == target:
            target.symlink_to(outside)
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(trainer.os, "open", swapped_open)
    clusters = trainer.cluster_failures([_rec()], min_count=1)
    with pytest.raises(OSError):
        trainer.append_cases(tmp_path, clusters)
    assert outside.read_text(encoding="utf-8") == "private external file"
    assert outside.stat().st_mode & 0o777 == 0o644


def test_windows_corpus_uses_native_lock_before_encrypting(tmp_path, monkeypatch, corpus_key):
    locked = []

    def lock(descriptor, mode, length):
        assert os.fstat(descriptor).st_size >= 1
        assert os.lseek(descriptor, 0, os.SEEK_CUR) == 0
        assert mode == 1 and length == 1
        locked.append(descriptor)

    monkeypatch.setitem(sys.modules, "msvcrt", SimpleNamespace(LK_LOCK=1, locking=lock))
    monkeypatch.setattr(trainer, "os", SimpleNamespace(**{**vars(os), "name": "nt"}))
    clusters = trainer.cluster_failures([_rec()], min_count=1)
    written = trainer.append_cases(tmp_path, clusters)
    path = tmp_path / "daily-orchestrator.jsonl"
    assert "任务正文" not in path.read_text(encoding="utf-8")
    assert trainer.load_cases(path) == written
    assert len(locked) == 2


def test_mine_cli_reports_counts_without_private_samples(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("MODSTORE_RETORT_GROWTHBOOK_URL", raising=False)
    ledger = tmp_path / "private-ledger.jsonl"
    record = _rec(employee="private-pack-sentinel", reason="private-reason-sentinel")
    record["report_excerpt"] = "private-task-sentinel"
    ledger.write_text("\n".join(json.dumps(record) for _ in range(2)), encoding="utf-8")
    assert trainer.main(["mine", "--ledger", str(ledger)]) == 0
    output = capsys.readouterr().out
    assert json.loads(output) == {
        "cluster_count": 1,
        "failure_count": 2,
        "sample_count": 2,
    }
    assert "private-" not in output
    assert str(ledger) not in output
    cluster = trainer.mine(ledger)[0]
    assert trainer.training_identity(cluster) == ("employee_prompt", "private-pack-sentinel")
    assert cluster["samples"][0]["task"] == "private-task-sentinel"


def test_select_pack_prefers_latest_version(tmp_path):
    for version in ("1.0.0", "1.0.2", "1.0.1"):
        folder = tmp_path / f"worker@{version}"
        folder.mkdir()
        (folder / "prompt.txt").write_text("p" + version, encoding="utf-8")
    assert trainer.select_pack(tmp_path, "worker").name == "worker@1.0.2"


def test_build_config_writes_promptfoo_inputs(tmp_path, monkeypatch):
    monkeypatch.setenv("XCAGI_LLM_MODEL", "approved-model")
    monkeypatch.setenv("XCAGI_LLM_BASE_URL", "https://platform.test/v1")
    built = trainer.build_config(
        out_dir=tmp_path,
        baseline_prompt="基线",
        candidate_prompt="候选",
        cases=[{"task": "任务一"}],
    )
    config = json.loads(Path(built["config"]).read_text(encoding="utf-8"))
    assert len(config["prompts"]) == 2
    assert config["tests"].startswith("file://")
    assert "{{task}}" in Path(built["baseline"]).read_text(encoding="utf-8")
    assert config["defaultTest"]["options"]["provider"] == config["providers"][0]
    assert config["providers"][0]["config"]["max_tokens"] == 1024


def paired_result():
    return {
        "results": {
            "results": [
                {
                    "promptIdx": i,
                    "testIdx": 0,
                    "success": bool(i),
                    "failureReason": 0 if i else 1,
                    "gradingResult": {"pass": bool(i)},
                    "error": None if i else "Deterministic assertion failed",
                    "provider": {"id": "model"},
                    "vars": {"case_id": "case", "task": "actual case"},
                }
                for i in range(2)
            ]
        }
    }


def test_decide_requires_paired_provider_case_and_frozen_bundle():
    result, bundle = (
        paired_result(),
        {
            "provider_id": "model",
            "case_ids": ["case"],
            "case_sha256": [trainer._hash("actual case")],
        },
    )
    assert trainer.decide(result)["verdict"] == "keep_baseline"
    assert trainer.decide(result, bundle=bundle)["verdict"] == "candidate_for_approval"
    unavailable = deepcopy(result)
    unavailable["results"]["results"][0]["failureReason"] = 2
    assert trainer.decide(unavailable, bundle=bundle)["verdict"] == "keep_baseline"
    for mutation in ("provider", "testIdx", "success", "vars"):
        changed = deepcopy(result)
        changed["results"]["results"][1][mutation] = {
            "provider": {"id": "other"},
            "testIdx": 1,
            "success": "true",
            "vars": {"case_id": "other"},
        }[mutation]
        assert trainer.decide(changed, bundle=bundle)["verdict"] == "keep_baseline"
    result["results"]["results"].append(deepcopy(result["results"]["results"][1]))
    assert trainer.decide(result, bundle=bundle)["verdict"] == "keep_baseline"


def frozen_evaluation(tmp_path, monkeypatch):
    monkeypatch.setenv("XCAGI_LLM_MODEL", "approved-model")
    monkeypatch.setenv("XCAGI_LLM_BASE_URL", "https://platform.test/v1")
    built = trainer.build_config(
        out_dir=tmp_path,
        baseline_prompt="baseline\r\n",
        candidate_prompt="candidate\r\n",
        cases=[{"task": "actual case"}],
    )
    bundle = json.loads(Path(built["bundle"]).read_text())
    result = paired_result()
    result["metadata"] = {"promptfooVersion": trainer.PROMPTFOO_VERSION}
    result["results"]["prompts"] = [
        {"raw": Path(built[key]).read_bytes().decode()} for key in ("baseline", "candidate")
    ]
    for row in result["results"]["results"]:
        row["provider"]["id"] = bundle["provider_id"]
        row["vars"]["case_id"] = bundle["case_ids"][0]
    output = tmp_path / "result.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return built, output


def test_frozen_input_result_hashes_survive_transport_and_detect_mutation(tmp_path, monkeypatch):
    from modstore_server.retort_training_candidates import _candidate

    built, result = frozen_evaluation(tmp_path, monkeypatch)
    original = trainer.seal_evaluation(Path(built["bundle"]), result)
    body = {
        "bundle_json": Path(built["bundle"]).read_bytes().decode(),
        "result_json": result.read_bytes().decode(),
        "files": {
            key: Path(built[key]).read_bytes().decode()
            for key in ("baseline", "candidate", "config", "tests")
        },
    }
    candidate = _candidate(json.loads(json.dumps(body)))
    assert candidate["offline_evidence"] == original
    assert candidate["control_prompt"] == "baseline\r\n"
    wrong_bundle = deepcopy(body)
    document = json.loads(wrong_bundle["bundle_json"])
    document["prompt_sha256"]["candidate"] = "0" * 64
    wrong_bundle["bundle_json"] = json.dumps(document)
    with pytest.raises(ValueError, match="prompt_hash_mismatch"):
        _candidate(wrong_bundle)
    body["files"]["candidate"] += "changed"
    with pytest.raises(ValueError, match="input_changed"):
        _candidate(body)


@pytest.mark.parametrize("result_vars", ["vars", "testCase"])
def test_paired_results_cannot_substitute_a_different_task_for_frozen_cases(
    tmp_path, monkeypatch, result_vars
):
    built, result_path = frozen_evaluation(tmp_path, monkeypatch)
    result = json.loads(result_path.read_bytes())
    for row in result["results"]["results"]:
        variables = row["vars"]
        variables["task"] = "Different task that was not in the frozen regression corpus"
        if result_vars == "testCase":
            row["testCase"] = {"vars": row.pop("vars")}
    result_path.write_text(json.dumps(result), encoding="utf-8")
    sealed = trainer.seal_evaluation(Path(built["bundle"]), result_path)
    assert sealed["verdict"] == "keep_baseline"
    assert sealed["reason"] == "evaluation_bundle_unbound"
    with pytest.raises(ValueError, match="training_candidate_not_improved"):
        trainer.candidate_for_experiment(Path(built["bundle"]), result_path)


def test_case_binding_preserves_exact_json_decoded_text_including_newlines():
    result = paired_result()
    task = "真实案例\r\n第二行\n"
    for row in result["results"]["results"]:
        row["vars"]["task"] = task
    bundle = {
        "provider_id": "model",
        "case_ids": ["case"],
        "case_sha256": [trainer._hash(task)],
    }
    transported = json.loads(json.dumps(result, ensure_ascii=True))
    assert trainer.decide(transported, bundle=bundle)["verdict"] == "candidate_for_approval"
    for row in transported["results"]["results"]:
        row["vars"]["task"] = task.replace("\r\n", "\n")
    assert trainer.decide(transported, bundle=bundle)["verdict"] == "keep_baseline"


def test_observation_without_reproduction_is_not_synthetic_case(tmp_path):
    clusters = trainer.cluster_failures([{**_rec(), "report_excerpt": ""}], min_count=1)
    assert trainer.append_cases(tmp_path, clusters) == []


def test_training_cost_bounds_and_unconfigured_model_fail_closed(tmp_path, monkeypatch):
    monkeypatch.delenv("XCAGI_LLM_MODEL", raising=False)
    with pytest.raises(ValueError, match="not_configured"):
        trainer.build_config(
            out_dir=tmp_path,
            baseline_prompt="b",
            candidate_prompt="c",
            cases=[{"task": "case"}],
        )
    monkeypatch.setenv("XCAGI_LLM_MODEL", "model")
    monkeypatch.setenv("XCAGI_LLM_BASE_URL", "https://platform.test/v1")
    with pytest.raises(ValueError, match="cases_required"):
        trainer.build_config(
            out_dir=tmp_path,
            baseline_prompt="b",
            candidate_prompt="c",
            cases=[{"task": "case"}] * 21,
        )


@pytest.mark.parametrize("employee", ["../outside", "/outside", r"a\b", "a/b", "", "a@1"])
def test_corpus_rejects_non_pack_paths(tmp_path, employee):
    clusters = trainer.cluster_failures([_rec(employee=employee)], min_count=1)
    with pytest.raises(ValueError, match="invalid_training"):
        trainer.append_cases(tmp_path, clusters or [{"employee_id": employee}])
    assert not list(tmp_path.iterdir())


def test_corpus_redacts_credentials_and_tightens_existing_permissions(tmp_path, corpus_key):
    path = tmp_path / "daily-orchestrator.jsonl"
    path.write_text("", encoding="utf-8")
    path.chmod(0o644)
    record = _rec(reason="authorization=private-credential")
    record["task_excerpt"] = "use password=private-password for test"
    clusters = trainer.cluster_failures([record], min_count=1)
    trainer.append_cases(tmp_path, clusters)
    content = path.read_text(encoding="utf-8")
    assert "private-credential" not in content and "private-password" not in content
    decrypted = json.dumps(trainer.load_cases(path), ensure_ascii=False)
    assert "private-credential" not in decrypted and "private-password" not in decrypted
    assert "[redacted]" in decrypted
    if os.name != "nt":
        assert path.stat().st_mode & 0o777 == 0o600
