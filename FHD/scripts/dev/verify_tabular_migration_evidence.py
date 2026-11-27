"""Check paired shadow observations against a frozen independent truth manifest.

This checks evidence consistency, not runner authenticity or production acceptance.
Keep customer originals and annotated facts in an authorized evidence directory,
never in git. The reviewer supplies the expected SHAs and manifest digest.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

CONSUMERS = frozenset({"elt", "office", "agent_attachment", "rag", "local_file", "template", "qc"})
FEATURES = frozenset({"excel_multi_table", "excel_hidden", "excel_merge", "excel_formula", "excel_blank", "excel_style", "excel_large", "word", "pdf", "image", "csv"})
SIDE_EFFECTS = {"writes", "charges", "external_sends"}


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def unique_object(pairs):
    result = dict(pairs)
    require(len(result) == len(pairs), "duplicate JSON key")
    return result


def reject_constant(_):
    raise ValueError("non-finite JSON value")


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_object,
                      parse_constant=reject_constant)


def same_value(left, right):
    # Python equality conflates bool/int and nested numeric types.
    return json.dumps(left, sort_keys=True, allow_nan=False) == json.dumps(right, sort_keys=True, allow_nan=False)


def scores(truth, observed):
    require(isinstance(observed, dict), "observations must be a fact map")
    matched = sum(key in observed and same_value(value, observed[key]) for key, value in truth.items())
    return {"expected": len(truth), "observed": len(observed), "matched": matched,
            "missing_or_wrong": len(truth) - matched, "extra_or_wrong": len(observed) - matched}


def verify(directory: Path, source_sha: str, baseline_sha: str, manifest_sha: str):
    require(all(re.fullmatch(r"[0-9a-f]{40}", value) for value in (source_sha, baseline_sha))
            and source_sha != baseline_sha, "candidate and baseline need distinct exact commits")
    manifest_path = directory / "manifest.json"
    require(digest(manifest_path) == manifest_sha, "independent manifest digest mismatch")
    manifest = read_json(manifest_path)
    require(type(manifest.get("schema_version")) is int and manifest["schema_version"] == 1 and isinstance(manifest.get("cases"), list), "invalid manifest")
    seen, coverage, consumers, source_hashes = set(), set(), set(), set()
    splits = {"public": 0, "customer_holdout": 0}
    comparisons = []
    for case in manifest["cases"]:
        case_id = case["id"]
        require(isinstance(case_id, str) and re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", case_id)
                and case_id not in seen, "invalid or duplicate case id")
        seen.add(case_id)
        require(case["split"] in {"public", "customer_holdout"}, "synthetic or unclassified corpus")
        input_sha = digest(directory / f"{case_id}.source")
        require(input_sha == case["input_sha256"] and input_sha not in source_hashes, "source mismatch or repeated input")
        source_hashes.add(input_sha)
        splits[case["split"]] += 1
        features = case["features"]
        require(isinstance(features, list) and features and set(features) <= FEATURES, "invalid feature coverage")
        coverage.update(features)
        truths = case["truth"]
        require(isinstance(truths, dict) and truths and set(truths) <= CONSUMERS, "invalid consumer coverage")
        for consumer, truth in truths.items():
            require(isinstance(truth, dict) and truth, "empty independent truth")
            consumers.add(consumer)
            comparison = {"case": case_id, "consumer": consumer}
            for lane, sha in (("baseline", baseline_sha), ("candidate", source_sha)):
                path = directory / f"{case_id}.{consumer}.{lane}.json"
                observation = read_json(path)
                expected = {"schema_version": 1, "source_sha": sha, "manifest_sha256": manifest_sha,
                            "input_sha256": input_sha, "case": case_id, "consumer": consumer,
                            "mode": "shadow", "tracked_source_dirty": False}
                require(all(key in observation and same_value(observation[key], value) for key, value in expected.items()),
                        "unrelated, dirty or non-shadow observation")
                effects = observation.get("side_effects")
                require(isinstance(effects, dict) and set(effects) == SIDE_EFFECTS
                        and all(type(value) is int and value == 0 for value in effects.values()), "shadow side effect")
                comparison[lane] = {**scores(truth, observation.get("facts")), "receipt_sha256": digest(path)}
            comparisons.append(comparison)
    require(coverage == FEATURES and consumers == CONSUMERS and all(splits.values()),
            "missing feature, consumer or customer holdout coverage")
    passed = all(not row["candidate"]["missing_or_wrong"] and not row["candidate"]["extra_or_wrong"] for row in comparisons)
    return {"status": "PARITY_PASS" if passed else "PARITY_FAIL", "source_sha": source_sha,
            "baseline_sha": baseline_sha, "manifest_sha256": manifest_sha, "corpus_splits": splits,
            "comparisons": comparisons, "production_acceptance": "UNVERIFIED"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--baseline-sha", required=True)
    parser.add_argument("--manifest-sha", required=True)
    args = parser.parse_args()
    try:
        result = verify(args.directory, args.source_sha, args.baseline_sha, args.manifest_sha)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        # Never print customer paths, cell values or untrusted receipt content.
        print(json.dumps({"status": "BLOCKED", "production_acceptance": "UNVERIFIED"}))
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "PARITY_PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
