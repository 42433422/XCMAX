#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""评估 NeuroBus 路由策略：准确率 + 推理延迟 P99 + 混淆矩阵。

加载指定版本的 policy（默认 ``active_version``），在测试集上评估：
- 路由准确率（vs LLM-D 仲裁 ground truth）
- NN 推理延迟 P99（CPU，单次 forward，1000 次采样）
- 混淆矩阵（reflex/subconscious/conscious）

测试集：``arbitrated_data.jsonl`` 中 ``accepted=true`` 的样本。
ground truth = ``label`` 字段；规则路由基线 = ``history_action`` 字段。

退出码：
- 准确率 ≥ 基线+5% 且延迟 P99 < 2ms → exit 0
- 否则 → exit 1

用法::

    python scripts/dev/eval_routing_policy.py --help
    python scripts/dev/eval_routing_policy.py \\
        --arbitrated resources/routing_policies/arbitrated_data.jsonl \\
        --version active --baseline-improve 0.05 --latency-p99-ms 2.0
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

FHD_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FHD_ROOT))

DEFAULT_ARBITRATED = FHD_ROOT / "resources" / "routing_policies" / "arbitrated_data.jsonl"
DEFAULT_MANIFEST = FHD_ROOT / "resources" / "routing_policies" / "manifest.json"

PROCESSORS = ("reflex", "subconscious", "conscious")
PROCESSOR_TO_IDX = {"reflex": 0, "subconscious": 1, "conscious": 2}
IDX_TO_PROCESSOR = {v: k for k, v in PROCESSOR_TO_IDX.items()}
ACTION_TO_PROCESSOR = {
    "reflex": "reflex",
    "subconscious": "subconscious",
    "conscious": "conscious",
    "0": "reflex",
    "1": "subconscious",
    "2": "conscious",
}


def _import_torch():
    try:
        import torch  # type: ignore[import-not-found]
        return torch
    except ImportError as e:  # pragma: no cover
        print(f"ERROR: 缺 torch 依赖：{e}", file=sys.stderr)
        sys.exit(2)


def _import_routing_mlp():
    from app.neuro_bus.routing.policy_nn import RoutingMLP  # noqa: WPS433
    return RoutingMLP


# --------------------------------------------------------------------------- #
# 加载策略
# --------------------------------------------------------------------------- #
def _resolve_version(manifest_path: Path, version: str) -> tuple[str, Path]:
    if not manifest_path.is_file():
        print(f"ERROR: manifest 不存在：{manifest_path}", file=sys.stderr)
        sys.exit(2)
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"ERROR: manifest 解析失败：{e}", file=sys.stderr)
        sys.exit(2)
    if version in ("active", "active_version", ""):
        ver = str(manifest.get("active_version") or "").strip()
        if not ver:
            print("ERROR: manifest 中无 active_version", file=sys.stderr)
            sys.exit(2)
    else:
        ver = str(version).strip()
    weights_rel = None
    for p in manifest.get("policies") or []:
        if str(p.get("version")) == ver:
            weights_rel = p.get("path") or f"policy_v{ver}.pt"
            break
    if not weights_rel:
        print(f"ERROR: manifest 中未找到版本 {ver}", file=sys.stderr)
        sys.exit(2)
    weights_path = manifest_path.parent / weights_rel
    if not weights_path.is_file():
        print(f"ERROR: 权重文件不存在：{weights_path}", file=sys.stderr)
        sys.exit(2)
    return ver, weights_path


def load_policy(manifest_path: Path, version: str) -> tuple[Any, str]:
    torch = _import_torch()
    RoutingMLP = _import_routing_mlp()
    ver, weights_path = _resolve_version(manifest_path, version)
    model = RoutingMLP()
    state = torch.load(weights_path, map_location="cpu")
    model.load_state_dict(state)
    model.eval()
    return model, ver


# --------------------------------------------------------------------------- #
# 加载测试集
# --------------------------------------------------------------------------- #
def _normalize_action(action: Any) -> str:
    if action is None:
        return ""
    s = str(action).strip().lower()
    return ACTION_TO_PROCESSOR.get(s, s)


def load_test_set(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        print(f"ERROR: 测试集文件不存在：{path}", file=sys.stderr)
        sys.exit(2)
    out: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not obj.get("accepted"):
                continue
            label = obj.get("label")
            if not label or label not in PROCESSOR_TO_IDX:
                continue
            features = list(obj.get("features") or [])
            if len(features) != 16:
                continue
            out.append(
                {
                    "features": features,
                    "label": label,
                    "label_idx": PROCESSOR_TO_IDX[label],
                    "history_action": _normalize_action(obj.get("history_action")),
                }
            )
    return out


# --------------------------------------------------------------------------- #
# 评估
# --------------------------------------------------------------------------- #
def evaluate_accuracy(
    model: Any, test_set: list[dict[str, Any]]
) -> tuple[float, float, list[int], list[int], list[list[int]]]:
    """返回 (nn_acc, rule_acc, nn_preds, rule_preds, confusion_matrix)。"""
    torch = _import_torch()
    if not test_set:
        return 0.0, 0.0, [], [], [[0, 0, 0], [0, 0, 0], [0, 0, 0]]

    X = torch.tensor([s["features"] for s in test_set], dtype=torch.float32)
    y_true = [s["label_idx"] for s in test_set]
    with torch.no_grad():
        logits = model(X)
        nn_preds = logits.argmax(dim=1).tolist()

    rule_preds: list[int] = []
    for s in test_set:
        ha = s["history_action"]
        rule_preds.append(PROCESSOR_TO_IDX.get(ha, -1))

    nn_correct = sum(1 for p, t in zip(nn_preds, y_true, strict=True) if p == t)
    nn_acc = nn_correct / len(y_true)
    rule_correct = sum(1 for p, t in zip(rule_preds, y_true, strict=True) if p == t)
    rule_acc = rule_correct / len(y_true)

    # 混淆矩阵：行=真实，列=预测（NN）
    cm = [[0, 0, 0], [0, 0, 0], [0, 0, 0]]
    for p, t in zip(nn_preds, y_true, strict=True):
        cm[t][p] += 1
    return nn_acc, rule_acc, nn_preds, rule_preds, cm


def measure_latency_p99(model: Any, n_samples: int = 1000) -> tuple[float, list[float]]:
    """CPU 上单次 forward，返回 (p99_ms, all_latencies_ms)。"""
    torch = _import_torch()
    import random

    rng = random.Random(42)
    # 随机生成 16 维特征
    x = torch.tensor(
        [[rng.random() for _ in range(16)]], dtype=torch.float32
    )
    latencies: list[float] = []
    # warmup
    with torch.no_grad():
        for _ in range(10):
            _ = model(x)
    # measure
    with torch.no_grad():
        for _ in range(n_samples):
            t0 = time.perf_counter()
            _ = model(x)
            t1 = time.perf_counter()
            latencies.append((t1 - t0) * 1000.0)
    latencies.sort()
    p99_idx = max(0, int(len(latencies) * 0.99) - 1)
    return latencies[p99_idx], latencies


# --------------------------------------------------------------------------- #
# 报告
# --------------------------------------------------------------------------- #
def render_report(
    version: str,
    test_size: int,
    nn_acc: float,
    rule_acc: float,
    confusion: list[list[int]],
    p99_ms: float,
    mean_ms: float,
    latency_samples: int,
    baseline_improve: float,
    latency_threshold_ms: float,
) -> str:
    lines: list[str] = []
    lines.append("=" * 60)
    lines.append("NeuroBus Routing Policy 评估报告")
    lines.append("=" * 60)
    lines.append(f"策略版本：v{version}")
    lines.append(f"测试集大小：{test_size}")
    lines.append("")
    lines.append("【准确率】")
    lines.append(f"  NN 路由准确率：{nn_acc:.2%}")
    lines.append(f"  规则路由基线：{rule_acc:.2%}")
    improve = nn_acc - rule_acc
    lines.append(f"  提升：{improve:+.2%}（阈值 ≥ +{baseline_improve:.0%}）")
    lines.append("")
    lines.append("【混淆矩阵（行=真实，列=NN预测）】")
    true_label = "真实\\预测"
    header = f"{true_label:<14}" + "".join(f"{p:<14}" for p in PROCESSORS)
    lines.append(header)
    for i, proc in enumerate(PROCESSORS):
        row = f"{proc:<14}" + "".join(f"{confusion[i][j]:<14}" for j in range(3))
        lines.append(row)
    lines.append("")
    lines.append("【推理延迟（CPU）】")
    lines.append(f"  P99：{p99_ms:.4f} ms（阈值 < {latency_threshold_ms} ms）")
    lines.append(f"  均值：{mean_ms:.4f} ms")
    lines.append(f"  采样次数：{latency_samples}")
    lines.append("")
    lines.append("【门禁判定】")
    acc_pass = improve >= baseline_improve
    lat_pass = p99_ms < latency_threshold_ms
    lines.append(f"  准确率提升 ≥ {baseline_improve:.0%}：{'PASS' if acc_pass else 'FAIL'}")
    lines.append(f"  P99 < {latency_threshold_ms} ms：{'PASS' if lat_pass else 'FAIL'}")
    overall = acc_pass and lat_pass
    lines.append(f"  总体：{'PASS' if overall else 'FAIL'}")
    lines.append("=" * 60)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="评估 NeuroBus 路由策略：准确率 + 延迟 P99 + 混淆矩阵",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--arbitrated",
        type=Path,
        default=DEFAULT_ARBITRATED,
        help="arbitrated_data.jsonl 路径（测试集来源）",
    )
    parser.add_argument(
        "--manifest", type=Path, default=DEFAULT_MANIFEST, help="manifest.json 路径"
    )
    parser.add_argument(
        "--version",
        default="active",
        help="策略版本（'active' 或具体版本号，默认 active）",
    )
    parser.add_argument(
        "--baseline-improve",
        type=float,
        default=0.05,
        help="准确率提升阈值（默认 0.05，即 5%%）",
    )
    parser.add_argument(
        "--latency-p99-ms",
        type=float,
        default=2.0,
        help="延迟 P99 阈值（默认 2.0 ms）",
    )
    parser.add_argument(
        "--latency-samples",
        type=int,
        default=1000,
        help="延迟测量采样次数（默认 1000）",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help="评估报告输出路径（默认仅 stdout）",
    )
    args = parser.parse_args(argv)

    model, ver = load_policy(args.manifest, args.version)
    print(f"[eval] 加载策略 v{ver}")

    test_set = load_test_set(args.arbitrated)
    print(f"[eval] 测试集 {len(test_set)} 条（accepted=true）")
    if not test_set:
        print("ERROR: 测试集为空，无法评估", file=sys.stderr)
        return 1

    nn_acc, rule_acc, _nn_preds, _rule_preds, cm = evaluate_accuracy(model, test_set)
    p99_ms, latencies = measure_latency_p99(model, args.latency_samples)
    mean_ms = sum(latencies) / len(latencies) if latencies else 0.0

    report = render_report(
        ver,
        len(test_set),
        nn_acc,
        rule_acc,
        cm,
        p99_ms,
        mean_ms,
        args.latency_samples,
        args.baseline_improve,
        args.latency_p99_ms,
    )
    print(report)
    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(report + "\n", encoding="utf-8")
        print(f"\n[eval] 报告已写入 {args.report}", file=sys.stderr)

    improve = nn_acc - rule_acc
    if improve >= args.baseline_improve and p99_ms < args.latency_p99_ms:
        print("[eval] PASS — 准确率与延迟均达标")
        return 0
    print(
        f"[eval] FAIL — 准确率提升 {improve:+.2%}（需 ≥ +{args.baseline_improve:.0%}），"
        f"P99 {p99_ms:.4f}ms（需 < {args.latency_p99_ms}ms）",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
