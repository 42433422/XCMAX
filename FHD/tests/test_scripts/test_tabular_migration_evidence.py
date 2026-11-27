"""Synthetic tests of the checker, never customer acceptance evidence."""

import json

import pytest

from scripts.dev import verify_tabular_migration_evidence as gate


@pytest.fixture
def bundle(tmp_path):
    def write(path, value):
        path.write_text(json.dumps(value), encoding="utf-8")

    truth = {name: {"sheet!A1": 0, "sheet!B2": False, "sheet!C3": ""} for name in gate.CONSUMERS}
    cases = []
    for case_id, split in (("public", "public"), ("holdout", "customer_holdout")):
        source = tmp_path / f"{case_id}.source"
        source.write_bytes(f"synthetic checker fixture: {case_id}".encode())
        cases.append(
            {
                "id": case_id,
                "split": split,
                "input_sha256": gate.digest(source),
                "features": sorted(gate.FEATURES),
                "truth": truth,
            }
        )
    manifest = tmp_path / "manifest.json"
    write(manifest, {"schema_version": 1, "cases": cases})
    manifest_sha = gate.digest(manifest)
    candidate, baseline = "a" * 40, "b" * 40
    for case in cases:
        for name, facts in truth.items():
            for lane, sha in (("baseline", baseline), ("candidate", candidate)):
                write(
                    tmp_path / f"{case['id']}.{name}.{lane}.json",
                    {
                        "schema_version": 1,
                        "source_sha": sha,
                        "manifest_sha256": manifest_sha,
                        "input_sha256": case["input_sha256"],
                        "case": case["id"],
                        "consumer": name,
                        "mode": "shadow",
                        "tracked_source_dirty": False,
                        "side_effects": dict.fromkeys(gate.SIDE_EFFECTS, 0),
                        "facts": facts if lane == "candidate" else {"sheet!A1": 0},
                    },
                )
    return tmp_path, candidate, baseline, manifest_sha


def test_candidate_exact_match_is_parity_only(bundle):
    result = gate.verify(*bundle)
    assert result["status"] == "PARITY_PASS"
    assert result["production_acceptance"] == "UNVERIFIED"
    assert len(result["comparisons"]) == 14
    assert all(row["baseline"]["missing_or_wrong"] == 2 for row in result["comparisons"])


@pytest.mark.parametrize(
    "facts",
    [
        {"sheet!A1": False, "sheet!B2": False, "sheet!C3": ""},
        {"sheet!A1": 0, "sheet!B2": False},
        {"sheet!A1": 0, "sheet!B2": False, "sheet!C3": "", "sheet!D4": None},
    ],
)
def test_wrong_type_missing_or_extra_fact_fails(bundle, facts):
    path = bundle[0] / "holdout.elt.candidate.json"
    value = gate.read_json(path)
    value["facts"] = facts
    path.write_text(json.dumps(value))
    assert gate.verify(*bundle)["status"] == "PARITY_FAIL"


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_sha", "c" * 40),
        ("tracked_source_dirty", True),
        ("mode", "live"),
        ("side_effects", {"writes": 0, "charges": 1, "external_sends": 0}),
        ("side_effects", {"writes": False, "charges": 0, "external_sends": 0}),
    ],
)
def test_wrong_identity_or_side_effect_blocks(bundle, field, value):
    path = bundle[0] / "holdout.elt.candidate.json"
    receipt = gate.read_json(path)
    receipt[field] = value
    path.write_text(json.dumps(receipt))
    with pytest.raises(ValueError):
        gate.verify(*bundle)


def test_original_tampering_blocks(bundle):
    (bundle[0] / "holdout.source").write_bytes(b"different")
    with pytest.raises(ValueError):
        gate.verify(*bundle)


def test_manifest_tampering_blocks(bundle):
    path = bundle[0] / "manifest.json"
    path.write_text("{}")
    with pytest.raises(ValueError):
        gate.verify(*bundle)


def test_missing_receipt_blocks(bundle):
    (bundle[0] / "holdout.qc.candidate.json").unlink()
    with pytest.raises(OSError):
        gate.verify(*bundle)


def test_duplicate_json_key_blocks(bundle):
    path = bundle[0] / "holdout.elt.candidate.json"
    path.write_text('{"facts": {}, "facts": {}}')
    with pytest.raises(ValueError, match="duplicate"):
        gate.verify(*bundle)
