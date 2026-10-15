# R22 shared-engine 域开源锚点实测：Temporal OSS 任务集 B1-B3
# 使用 temporalio SDK WorkflowEnvironment.start_local()（内置 dev server + sqlite 持久化）
# 输出单行 JSON（RESULT:<json>）
import asyncio
import hashlib
import json
import time

from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, Worker

import r22_defs as d

out = {"benchmark": "temporal-oss", "tasks": {}}
RUN = str(int(time.time()))


async def main():
    env = await asyncio.wait_for(WorkflowEnvironment.start_local(), timeout=120)
    client = env.client
    worker = Worker(
        client, task_queue=d.TASK_QUEUE,
        activities=[d.compose, d.flaky], workflows=[d.EngineWorkflow, d.RetryWorkflow],
    )
    async with worker:
        # ---------- B1 执行协议 + 状态持久化 + 插件接口 ----------
        try:
            h = await client.start_workflow(
                d.EngineWorkflow.run, ["a", "b", "c"], id=f"r22-b1-{RUN}", task_queue=d.TASK_QUEUE
            )
            mid = await asyncio.wait_for(h.query("progress"), timeout=30)
            result = await asyncio.wait_for(h.result(), timeout=60)
            hist = await client.get_workflow_handle(f"r22-b1-{RUN}").fetch_history()
            out["tasks"]["B1"] = {
                "verdict": "PASS" if result == ["a|X", "b|X", "c|X"] and len(hist.events) > 5 else "FAIL",
                "result": result,
                "query_midflight": mid,
                "history_events": len(hist.events),
                "mechanism": "状态持久化于 event history；query 读中间态；activity=插件接口",
            }
        except Exception as e:  # noqa: BLE001
            out["tasks"]["B1"] = {"verdict": "FAIL", "error": f"{type(e).__name__}: {e}"[:300]}
        print("B1", out["tasks"]["B1"].get("verdict"), flush=True)

        # ---------- B2 重试不虚报完成/不重做副作用 + 历史重放确定性 ----------
        try:
            h2 = await client.start_workflow(
                d.RetryWorkflow.run, 21, id=f"r22-b2-{RUN}", task_queue=d.TASK_QUEUE
            )
            r2 = await asyncio.wait_for(h2.result(), timeout=60)
            effects_ok = d.side_effects == [21] and d.attempts["activity"] == 3
            hist2 = await client.get_workflow_handle(f"r22-b2-{RUN}").fetch_history()
            replayer = Replayer(workflows=[d.RetryWorkflow])
            replayed = await asyncio.wait_for(
                replayer.replay_workflow(hist2), timeout=60
            )
            replay_ok = replayed.replay_failure is None
            out["tasks"]["B2"] = {
                "verdict": "PASS" if r2 == 42 and effects_ok and replay_ok else "FAIL",
                "workflow_result": r2,
                "activity_attempts": d.attempts["activity"],
                "side_effect_count": len(d.side_effects),
                "replay_deterministic": replay_ok,
                "mechanism": "重试第 3 次成功、副作用仅 1 次；历史重放通过确定性校验",
            }
        except Exception as e:  # noqa: BLE001
            out["tasks"]["B2"] = {"verdict": "FAIL", "error": f"{type(e).__name__}: {e}"[:300]}
        print("B2", out["tasks"]["B2"].get("verdict"), flush=True)

        # ---------- B3 执行证据与输入/产物哈希绑定 ----------
        try:
            hist3 = await client.get_workflow_handle(f"r22-b2-{RUN}").fetch_history()
            from temporalio.api.history.v1 import History

            hpb = History()
            for e in hist3.events:
                hpb.events.add().CopyFrom(e)
            digest = hashlib.sha256(hpb.SerializeToString()).hexdigest()
            started = [
                e for e in hist3.events
                if e.HasField("workflow_execution_started_event_attributes")
            ]
            payloads = started[0].workflow_execution_started_event_attributes.input.payloads
            args = [json.loads(p.data.decode()) for p in payloads]
            bound = bool(digest) and args == [21]
            out["tasks"]["B3"] = {
                "verdict": "PASS" if bound else "FAIL",
                "history_sha256": digest[:32],
                "input_args": args,
                "mechanism": "history 可哈希绑定；输入从历史还原（证据=输入+执行记录）",
            }
        except Exception as e:  # noqa: BLE001
            out["tasks"]["B3"] = {"verdict": "FAIL", "error": f"{type(e).__name__}: {e}"[:300]}
        print("B3", out["tasks"]["B3"].get("verdict"), flush=True)

    await asyncio.wait_for(env.shutdown(), timeout=30)


asyncio.run(main())
print("RESULT:" + json.dumps(out, ensure_ascii=False, default=str))
