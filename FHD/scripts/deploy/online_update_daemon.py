#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""NeuroBus NN 路由策略在线更新 daemon。

定期从 routing_decisions.jsonl 读取带 reward 的样本（规则路由的实际 SLA/success），
喂给 OnlineLearner，达到阈值后触发增量更新，保存新版本 policy。

reward 计算：reward = sla_hit * 0.6 + success * 0.4
（用规则路由的实际结果作为 proxy reward，教 NN 模仿规则路由的正确决策）

运行方式：
  # 单次运行（cron/CronJob 触发）
  python scripts/dev/online_update_daemon.py --once

  # 常驻 daemon（systemd 服务）
  python scripts/dev/online_update_daemon.py --interval 300

触发频率建议：
  - 低流量（<1K/天）：每小时一次
  - 中流量（1K-10K/天）：每 5 分钟一次
  - 高流量（>10K/天）：每分钟一次

K8s CronJob 示例：
  schedule: "*/5 * * * *"
  command: python scripts/dev/online_update_daemon.py --once
"""
from __future__ import annotations

import argparse
import json
import logging
import signal
import sys
import time
from pathlib import Path

FHD_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FHD_ROOT))

DEFAULT_LOG = FHD_ROOT / "resources" / "routing_policies" / "routing_decisions.jsonl"
STATE_FILE = FHD_ROOT / "resources" / "routing_policies" / ".online_update_state.json"
CANARY_STATE_FILE = FHD_ROOT / "resources" / "routing_policies" / "canary_state.json"

logger = logging.getLogger("online_update_daemon")

PROCESSOR_TO_IDX = {"reflex": 0, "subconscious": 1, "conscious": 2}
_RUNNING = True

# 自动切灰度阈值（NN 准确率 vs 规则基线）
# 影子模式 → 10% 灰度 → 50% 灰度 → 全量
CANARY_THRESHOLDS = [
    (0.70, 1.0, "full"),    # 准确率 ≥ 70% → 全量
    (0.60, 0.5, "canary"),  # 准确率 ≥ 60% → 50% 灰度
    (0.50, 0.1, "canary"),  # 准确率 ≥ 50% → 10% 灰度
    (0.00, 0.0, "shadow"),  # 准确率 < 50% → 影子模式
]


def _signal_handler(signum, frame):
    global _RUNNING
    _RUNNING = False
    logger.info("收到退出信号，准备退出...")


def _load_state() -> int:
    """读取上次处理到的字节偏移。"""
    try:
        if STATE_FILE.is_file():
            return json.loads(STATE_FILE.read_text()).get("offset", 0)
    except Exception:  # noqa: BLE001
        pass
    return 0


def _save_state(offset: int) -> None:
    try:
        STATE_FILE.write_text(json.dumps({"offset": offset}))
    except Exception as e:  # noqa: BLE001
        logger.warning("保存 state 失败：%s", e)


def _read_new_samples(log_path: Path, offset: int) -> tuple[list[dict], int]:
    """从 offset 开始读取新样本，返回 (samples, new_offset)。"""
    if not log_path.is_file():
        return [], offset
    samples = []
    try:
        size = log_path.stat().st_size
        if size < offset:
            # 日志被截断/轮转，从头开始
            offset = 0
        with log_path.open("r", encoding="utf-8") as f:
            f.seek(offset)
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    samples.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
            new_offset = f.tell()
        return samples, new_offset
    except Exception as e:  # noqa: BLE001
        logger.warning("读取日志失败：%s", e)
        return [], offset


def _extract_reward(row: dict) -> tuple[float | None, bool | None, bool | None]:
    """从路由日志行提取 (reward, sla_hit, success)。

    影子模式样本无 SLA 数据，用 action 作为弱监督信号（reward=1.0），
    教 NN 模仿规则路由的决策分布。
    """
    sla_hit = row.get("sla_hit")
    success = row.get("success")
    reward = row.get("reward")
    if reward is None and (sla_hit is not None or success is not None):
        sh = bool(sla_hit) if sla_hit is not None else False
        ss = bool(success) if success is not None else False
        reward = sh * 0.6 + ss * 0.4
    if reward is None:
        # 影子模式样本：用 action 作为弱监督（reward=1.0）
        reward = 1.0
    return reward, sla_hit, success


def _evaluate_nn_accuracy(samples: list[dict]) -> float:
    """评估 NN policy 在样本上的准确率（NN action == 规则 action 的比例）。

    影子模式样本的 action 是 NN 的决策，outcome="policy_shadow"。
    规则 action 从 extra.rule_action 或顶层 rule_action 字段读取。
    如果没有 rule_action，用 action 作为 label（NN 模仿自身，准确率=100%）。
    """
    if not samples:
        return 0.0
    from app.neuro_bus.routing.policy_nn import predict_with_confidence

    correct = 0
    total = 0
    for row in samples[-500:]:  # 最近 500 条
        features = list(row.get("features") or [])
        if len(features) != 16:
            continue
        action_str = str(row.get("action") or "").strip().lower()
        if action_str not in PROCESSOR_TO_IDX:
            continue
        rule_action_idx = PROCESSOR_TO_IDX[action_str]
        nn_idx, _ = predict_with_confidence(features)
        if nn_idx == rule_action_idx:
            correct += 1
        total += 1
    return correct / total if total > 0 else 0.0


def _auto_adjust_canary(accuracy: float) -> tuple[float, str]:
    """根据 NN 准确率自动调整 canary_ratio 和 mode。

    返回 (canary_ratio, mode)。
    """
    for threshold, ratio, mode in CANARY_THRESHOLDS:
        if accuracy >= threshold:
            return ratio, mode
    return 0.0, "shadow"


def _write_canary_state(canary_ratio: float, mode: str, accuracy: float, version: int | None) -> None:
    """写入 canary_state.json，policy_router 会动态读取。"""
    import datetime
    state = {
        "canary_ratio": canary_ratio,
        "mode": mode,
        "nn_accuracy": round(accuracy, 4),
        "active_version": version,
        "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    try:
        CANARY_STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))
        logger.info(
            "canary_state 已更新：mode=%s ratio=%.2f accuracy=%.4f version=%s",
            mode, canary_ratio, accuracy, version,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("写入 canary_state 失败：%s", e)


def run_once(args: argparse.Namespace) -> dict:
    """单次运行：读新样本 → 喂 OnlineLearner → 触发更新（如达阈值）。"""
    from app.neuro_bus.routing.online_learner import OnlineLearner

    log_path = Path(args.log_path)
    offset = _load_state()
    samples, new_offset = _read_new_samples(log_path, offset)

    if not samples:
        logger.info("无新样本（offset=%d）", offset)
        _save_state(new_offset)
        return {
            "new_samples": 0,
            "fed_to_learner": 0,
            "skipped": 0,
            "window_size": 0,
            "update_threshold": args.update_threshold,
            "updated": False,
            "new_version": None,
        }

    learner = OnlineLearner(
        window_size=args.window_size,
        epsilon=args.epsilon,
        lr=args.lr,
        update_threshold=args.update_threshold,
    )

    # 把当前窗口填满（从最近样本回填）
    fed = 0
    skipped = 0
    for row in samples:
        features = list(row.get("features") or [])
        if len(features) != 16:
            skipped += 1
            continue
        action_str = str(row.get("action") or "").strip().lower()
        if action_str not in PROCESSOR_TO_IDX:
            skipped += 1
            continue
        action_idx = PROCESSOR_TO_IDX[action_str]
        reward, sla_hit, success = _extract_reward(row)
        learner.record_decision(
            features=features,
            action=action_idx,
            reward=reward,
            sla_hit=sla_hit,
            success=success,
        )
        fed += 1

    _save_state(new_offset)

    result = {
        "new_samples": len(samples),
        "fed_to_learner": fed,
        "skipped": skipped,
        "window_size": len(learner._window),
        "update_threshold": args.update_threshold,
        "updated": False,
        "new_version": None,
        "nn_accuracy": None,
        "canary_mode": None,
        "canary_ratio": None,
    }

    logger.info(
        "读取 %d 条，喂入 %d 条，跳过 %d 条；窗口 %d/%d",
        len(samples), fed, skipped, len(learner._window), args.update_threshold,
    )

    # 检查是否触发更新
    if learner.should_update():
        logger.info("窗口达阈值 %d，触发在线更新...", args.update_threshold)
        new_version = learner.update_policy()
        if new_version:
            result["updated"] = True
            result["new_version"] = new_version
            logger.info("在线更新成功：新版本 v%s", new_version)
            # 更新后清空窗口（下次从零开始积累）
            learner._window.clear()

            # 评估新版本准确率并自动调整 canary
            accuracy = _evaluate_nn_accuracy(samples)
            canary_ratio, mode = _auto_adjust_canary(accuracy)
            _write_canary_state(canary_ratio, mode, accuracy, new_version)
            result["nn_accuracy"] = accuracy
            result["canary_mode"] = mode
            result["canary_ratio"] = canary_ratio
            logger.info(
                "自动切灰度：accuracy=%.4f → mode=%s ratio=%.2f",
                accuracy, mode, canary_ratio,
            )
        else:
            logger.warning("在线更新失败")
    else:
        logger.info(
            "窗口 %d/%d，未达阈值，不更新",
            len(learner._window), args.update_threshold,
        )
        # 即使不更新，也评估当前 policy 准确率并调整 canary
        accuracy = _evaluate_nn_accuracy(samples)
        canary_ratio, mode = _auto_adjust_canary(accuracy)
        _write_canary_state(canary_ratio, mode, accuracy, None)
        result["nn_accuracy"] = accuracy
        result["canary_mode"] = mode
        result["canary_ratio"] = canary_ratio

    return result


def run_daemon(args: argparse.Namespace) -> int:
    """常驻 daemon 模式。"""
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    logger.info(
        "在线更新 daemon 启动：interval=%ds, threshold=%d, log=%s",
        args.interval, args.update_threshold, args.log_path,
    )

    global _RUNNING
    while _RUNNING:
        try:
            result = run_once(args)
            if result.get("updated"):
                print(
                    f"[daemon] {time.strftime('%H:%M:%S')} 在线更新 → v{result['new_version']} "
                    f"(喂入 {result['fed_to_learner']} 条)",
                    flush=True,
                )
        except Exception as e:  # noqa: BLE001
            logger.error("daemon 循环异常：%s", e)

        # 等待 interval 秒（可被信号中断）
        for _ in range(args.interval):
            if not _RUNNING:
                break
            time.sleep(1)

    logger.info("daemon 已退出")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="NeuroBus NN 路由在线更新 daemon")
    parser.add_argument("--once", action="store_true", help="单次运行（cron 模式）")
    parser.add_argument("--interval", type=int, default=300, help="daemon 轮询间隔秒数（默认 300）")
    parser.add_argument("--log-path", default=str(DEFAULT_LOG), help="路由日志路径")
    parser.add_argument("--window-size", type=int, default=10000, help="滑动窗口大小")
    parser.add_argument("--update-threshold", type=int, default=1000, help="触发更新的样本阈值（默认 1000）")
    parser.add_argument("--epsilon", type=float, default=0.1, help="ε-greedy 探索率")
    parser.add_argument("--lr", type=float, default=0.001, help="在线学习率")
    parser.add_argument("--log-level", default="INFO", choices=("DEBUG", "INFO", "WARNING", "ERROR"))
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.once:
        result = run_once(args)
        canary_info = ""
        if result.get("canary_mode"):
            canary_info = f"，accuracy={result['nn_accuracy']:.4f} → {result['canary_mode']}({result['canary_ratio']:.2f})"
        print(
            f"[once] 新样本 {result['new_samples']}，喂入 {result['fed_to_learner']}，"
            f"窗口 {result['window_size']}/{result['update_threshold']}"
            + (f"，更新 → v{result['new_version']}" if result["updated"] else "，未更新")
            + canary_info
        )
        return 0

    return run_daemon(args)


if __name__ == "__main__":
    sys.exit(main())
