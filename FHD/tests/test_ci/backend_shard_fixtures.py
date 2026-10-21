"""Small complete artifacts for adversarial shard-gate tests."""

import json

from scripts.ci.backend_shards import partition, seal

IDENTITY = {
    "GITHUB_SHA": "a" * 40,
    "GITHUB_RUN_ID": "1",
    "GITHUB_RUN_ATTEMPT": "1",
    "BACKEND_SOURCE_SHA": "a" * 40,
}


def make_artifacts(root, total):
    nodes = [f"test_{n:02}.py::test_a" for n in range(max(4, total))]
    for index in range(1, total + 1):
        directory = root / f"shard-{index}"
        directory.mkdir(parents=True)
        selected = partition(nodes, total)[index - 1]
        data = dict(
            IDENTITY,
            index=index,
            total=total,
            partition_profile="count-v1",
            full=nodes,
            selected=selected,
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
