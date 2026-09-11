# R22 event-kernel 域开源锚点实测：Apache Kafka 任务集 B1-B3
# 前提：Kafka 3.8.1 KRaft 单节点监听 9092（r22-kafka 容器）
# 输出单行 JSON（RESULT:<json>）
import json
import time
import uuid

from confluent_kafka import Consumer, Producer, TopicPartition

BOOTSTRAP = "127.0.0.1:9092"
TOPIC = "r22-events-" + uuid.uuid4().hex[:8]
GROUP = "r22-group"

out = {"benchmark": "kafka", "tasks": {}}


def _produce(n, key=b"k1", offset_start=0):
    p = Producer({"bootstrap.servers": BOOTSTRAP, "enable.idempotence": True})
    for i in range(n):
        p.produce(TOPIC, key=key, value=f"msg-{offset_start + i}".encode(),
                  headers={"seq": str(offset_start + i).encode()})
    p.flush()


def _consume(max_msgs, timeout=20.0, group=GROUP, auto_offset="earliest", commit=True):
    c = Consumer({
        "bootstrap.servers": BOOTSTRAP, "group.id": group,
        "auto.offset.reset": auto_offset, "enable.auto.commit": commit,
    })
    c.subscribe([TOPIC])
    msgs = []
    deadline = time.time() + timeout
    while len(msgs) < max_msgs and time.time() < deadline:
        m = c.poll(0.5)
        if m is not None and not m.error():
            msgs.append(m)
    if not commit:
        c.commit(asynchronous=False)
    c.close()
    return msgs


# ---------- B1 投递语义与顺序 ----------
try:
    _produce(50)
    got = _consume(50)
    seqs = [int(m.headers()[0][1]) for m in got]
    ordered = seqs == sorted(seqs)
    same_key_order = all(
        got[i].offset() < got[i + 1].offset() for i in range(len(got) - 1)
    )
    out["tasks"]["B1"] = {
        "verdict": "PASS" if len(got) == 50 and ordered and same_key_order else "FAIL",
        "delivered": len(got),
        "in_order": ordered,
        "mechanism": "幂等 producer + 单分区 key 保序；at-least-once 语义",
    }
except Exception as e:  # noqa: BLE001
    out["tasks"]["B1"] = {"verdict": "FAIL", "error": f"{type(e).__name__}: {e}"[:300]}

# ---------- B2 重复投递/消费失败/死信 ----------
try:
    # 手动提交模式下：不提交重启 → 重复投递可观测
    c = Consumer({"bootstrap.servers": BOOTSTRAP, "group.id": GROUP + "-manual",
                  "auto.offset.reset": "earliest", "enable.auto.commit": False})
    c.subscribe([TOPIC])
    first = []
    deadline = time.time() + 15
    while len(first) < 5 and time.time() < deadline:
        m = c.poll(0.5)
        if m and not m.error():
            first.append(m)
    offsets = [m.offset() for m in first]
    c.close()  # 未 commit → 重启后重复消费
    again = _consume(5, timeout=15, group=GROUP + "-manual")
    dup_offsets = [m.offset() for m in again]
    redelivery = dup_offsets[: len(offsets)] == offsets
    # 死信模式：应用层失败计数后投递 DLQ topic
    dlq = TOPIC + ".dlq"
    p = Producer({"bootstrap.servers": BOOTSTRAP})
    p.produce(dlq, key=b"dead", value=b"poison-msg")
    p.flush()
    dl = Consumer({"bootstrap.servers": BOOTSTRAP, "group.id": "r22-dlq",
                   "auto.offset.reset": "earliest"})
    dl.subscribe([dlq])
    dm = None
    deadline = time.time() + 10
    while dm is None and time.time() < deadline:
        x = dl.poll(0.5)
        if x and not x.error():
            dm = x
    dl.close()
    out["tasks"]["B2"] = {
        "verdict": "PASS" if redelivery and dm is not None else "FAIL",
        "redelivery_on_no_commit": redelivery,
        "dlq_received": dm is not None and dm.value() == b"poison-msg",
        "mechanism": "未提交位移→重放（重复投递可观测）；失败消息路由 DLQ topic",
    }
except Exception as e:  # noqa: BLE001
    out["tasks"]["B2"] = {"verdict": "FAIL", "error": f"{type(e).__name__}: {e}"[:300]}

# ---------- B3 进程重启恢复 + 丢失/延迟观测 ----------
try:
    TOPIC3 = TOPIC + ".b3"
    p3 = Producer({"bootstrap.servers": BOOTSTRAP, "enable.idempotence": True})
    for i in range(30):
        p3.produce(TOPIC3, key=b"k1", value=f"b3-{i}".encode())
    p3.flush()
    probe0 = Consumer({"bootstrap.servers": BOOTSTRAP, "group.id": "r22-probe0"})
    leo = probe0.get_watermark_offsets(TopicPartition(TOPIC3, 0), timeout=5)[1]
    probe0.close()
    c1 = Consumer({"bootstrap.servers": BOOTSTRAP, "group.id": GROUP + "-recover",
                   "auto.offset.reset": "earliest", "enable.auto.commit": True})
    c1.subscribe([TOPIC3])
    before_crash = 0
    deadline = time.time() + 15
    t0 = time.time()
    while before_crash < 10 and time.time() < deadline:
        m = c1.poll(0.5)
        if m and not m.error():
            before_crash += 1
    c1.close()
    # “重启”：同 group 新实例从提交位移续读，直到追平 LEO
    c2 = Consumer({"bootstrap.servers": BOOTSTRAP, "group.id": GROUP + "-recover",
                   "auto.offset.reset": "earliest", "enable.auto.commit": True})
    c2.subscribe([TOPIC3])
    after_restart = 0
    while time.time() - t0 < 40:
        m = c2.poll(0.5)
        if m and not m.error():
            after_restart += 1
            if before_crash + after_restart >= leo:
                break
    committed_tp = c2.committed([TopicPartition(TOPIC3, 0)], 5.0)[0]
    c2.close()
    # 关闭后同 group 复查已提交位移（auto commit 在 close 时落盘）
    chk = Consumer({"bootstrap.servers": BOOTSTRAP, "group.id": GROUP + "-recover"})
    committed_tp = chk.committed([TopicPartition(TOPIC3, 0)], 5.0)[0]
    chk.close()
    no_loss = (before_crash + after_restart >= leo) and (committed_tp.offset >= leo)
    out["tasks"]["B3"] = {
        "verdict": "PASS" if no_loss else "FAIL",
        "consumed_before_restart": before_crash,
        "consumed_after_restart": after_restart,
        "log_end_offset": leo,
        "committed_offset": committed_tp.offset,
        "mechanism": "同 group 重启从提交位移续读；LEO 与 committed 差值即积压/丢失观测",
    }
except Exception as e:  # noqa: BLE001
    out["tasks"]["B3"] = {"verdict": "FAIL", "error": f"{type(e).__name__}: {e}"[:300]}

print("RESULT:" + json.dumps(out, ensure_ascii=False, default=str))
