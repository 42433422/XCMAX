"""Small complete artifacts for adversarial shard-gate tests."""

import json

from scripts.ci.backend_shards import object_digest, partition, seal, source_inventory

IDENTITY = {
    "GITHUB_SHA": "a" * 40,
    "GITHUB_RUN_ID": "1",
    "GITHUB_RUN_ATTEMPT": "1",
    "BACKEND_SOURCE_SHA": "a" * 40,
}


def artifact_source(root):
    return root.with_name(root.name + "-source")


def make_artifacts(root, total):
    source = artifact_source(root)
    source.mkdir()
    (source / "pytest.ini").write_text("[pytest]\n")
    for n in range(max(4, total)):
        (source / f"test_{n:02}.py").write_text("def test_a(): pass\n")
    configuration, files = source_inventory(source)
    for index in range(1, total + 1):
        directory = root / f"shard-{index}"
        directory.mkdir(parents=True)
        assigned = sorted(partition(list(files), total)[index - 1])
        selected = [f"{name}::test_a" for name in assigned]
        data = dict(
            IDENTITY,
            schema=2,
            index=index,
            total=total,
            partition_profile="count-v1",
            configuration=configuration,
            files=files,
            source_inventory_sha256=object_digest({"configuration": configuration, "files": files}),
            assigned_files=assigned,
            collected=selected,
            selected=selected,
            excluded_ramp=[],
            collection_reports={
                name: [
                    {
                        "outcome": "passed",
                        "children": [{"nodeid": f"{name}::test_a", "collector": False}],
                    }
                ]
                for name in assigned
            },
            exitstatus=0,
            collection_errors=[],
            collection_skips=[],
            subtests=[],
            reports={
                n: [
                    {"when": phase, "outcome": "passed", "duration": 0.1}
                    for phase in ("setup", "call", "teardown")
                ]
                for n in selected
            },
        )
        for mode in ("full", "behavior"):
            (directory / f"{mode}.json").write_text(json.dumps({**data, "mode": mode}))
            (directory / f".coverage.{mode}").write_bytes(b"coverage-test")
            (directory / f"{mode}.xml").write_text("<testsuite/>")
        seal(directory)
    return root
