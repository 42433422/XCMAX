"""Read the frozen verification protocol from the management service, never the candidate."""

import json
import os
import re
from pathlib import Path
from urllib.request import Request, urlopen


def prepare(env=os.environ, opener=urlopen):
    request_id = env["PARA_GITHUB_REQUEST_ID"]
    if (
        not re.fullmatch(r"[0-9a-f-]{36}", request_id)
        or env["GITHUB_RUN_ATTEMPT"] != "1"
    ):
        raise ValueError("invalid verification identity")
    request = Request(
        f"https://xiu-ci.com/api/service/mac-control/github-runs/{request_id}",
        headers={"Authorization": "Bearer " + env["MODSTORE_PARA_DISPATCH_TOKEN"]},
    )
    with opener(request, timeout=30) as response:
        state = json.load(response)
    if (
        state.get("request_id") != request_id
        or str(state.get("run_id")) != env["GITHUB_RUN_ID"]
        or state.get("repository") != env["GITHUB_REPOSITORY"]
        or state.get("finished") is not True
        or state.get("conclusion") != "success"
    ):
        raise ValueError("unconfirmed employee execution")
    protocol = state.get("benchmark_protocol")
    with Path(env["GITHUB_OUTPUT"]).open("a") as output:
        output.write(f"retort={'true' if protocol else 'false'}\n")
        if not protocol:
            return
        from retort_engine.evolution_contract import digest

        if (
            protocol["request_id"] != request_id
            or protocol["source_sha"] != env["GITHUB_SHA"]
            or protocol["repository"] != env["GITHUB_REPOSITORY"]
            or digest({k: v for k, v in protocol.items() if k != "protocol_digest"})
            != protocol["protocol_digest"]
            or not re.fullmatch(r"[0-9a-f]{40}", state.get("target_sha", ""))
            or state["target_sha"] == protocol["source_sha"]
            or not re.fullmatch(
                r"[a-zA-Z0-9./:_-]+@sha256:[0-9a-f]{64}",
                protocol.get("container_image", ""),
            )
        ):
            raise ValueError("frozen protocol identity or test image mismatch")
        Path(env["RUNNER_TEMP"], "retort-protocol.json").write_text(
            json.dumps(protocol)
        )
        output.write(
            f"target_sha={state['target_sha']}\nimage={protocol['container_image']}\n"
        )


if __name__ == "__main__":
    prepare()
