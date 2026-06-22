#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""训练 NeuroBus 路由策略 MLP（16→32→3）。

数据来源：
- ``labeled_data.jsonl``：取 ``gold`` 与 ``silver`` 样本（silver 权重 0.7）
- ``arbitrated_data.jsonl``：取 ``accepted=true`` 的仲裁样本（权重 1.0）

特征 = ``features`` 字段（16 维），标签 = processor 映射：
- reflex=0, subconscious=1, conscious=2

训练配置：
- 模型：``app.neuro_bus.routing.policy_nn.RoutingMLP``（16→32→3）
- 损失：``CrossEntropyLoss``（带样本权重）
- 优化器：``Adam(lr=0.001)``
- epochs：50（可 ``--epochs`` 覆盖）
- 80/20 训练/验证集分割（``--val-ratio`` 可调）

产物：
- ``resources/routing_policies/policy_vN.pt``：state_dict
- ``resources/routing_policies/manifest.json``：追加新版本并切换 ``active_version``
- stdout：训练报告（loss 曲线 + 验证准确率）

用法::

    python scripts/dev/train_routing_policy.py --help
    python scripts/dev/train_routing_policy.py \\
        --labeled resources/routing_policies/labeled_data.jsonl \\
        --arbitrated resources/routing_policies/arbitrated_data.jsonl \\
        --epochs 50 --val-ratio 0.2 --seed 42
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
import time
from pathlib import Path
from typing import Any

FHD_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FHD_ROOT))

DEFAULT_LABELED = FHD_ROOT / "resources" / "routing_policies" / "labeled_data.jsonl"
DEFAULT_ARBITRATED = FHD_ROOT / "resources" / "routing_policies" / "arbitrated_data.jsonl"
POLICY_DIR = FHD_ROOT / "resources" / "routing_policies"
MANIFEST_PATH = POLICY_DIR / "manifest.json"

PROCESSOR_TO_IDX = {"reflex": 0, "subconscious": 1, "conscious": 2}
SILVER_WEIGHT = 0.7


def _import_torch():
    try:
        import torch  # type: ignore[import-not-found]
        from torch import nn  # type: ignore[import-not-found]
        return torch, nn
    except ImportError as e:  # pragma: no cover
        print(f"ERROR: 缺 torch 依赖：{e}", file=sys.stderr)
        sys.exit(1)


def _import_routing_mlp():
    from app.neuro_bus.routing.policy_nn import RoutingMLP  # noqa: WPS433
    return RoutingMLP


# --------------------------------------------------------------------------- #
# 数据加载
# --------------------------------------------------------------------------- #
def _load_labeled(path: Path) -> list[tuple[list[float], int, float]]:
    """返回 (features, label_idx, weight) 列表。silver 权重 0.7，gold 权重 1.0。"""
    out: list[tuple[list[float], int, float]] = []
    if not path.is_file():
        return out
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            consensus = obj.get("consensus")
            label = obj.get("label")
            if consensus not in ("gold", "silver"):
                continue
            if not label or label not in PROCESSOR_TO_IDX:
                continue
            features = list(obj.get("features") or [])
            if len(features) != 16:
                continue
            weight = 1.0 if consensus == "gold" else SILVER_WEIGHT
            out.append((features, PROCESSOR_TO_IDX[label], weight))
    return out


def _load_arbitrated(path: Path) -> list[tuple[list[float], int, float]]:
    out: list[tuple[list[float], int, float]] = []
    if not path.is_file():
        return out
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
            out.append((features, PROCESSOR_TO_IDX[label], 1.0))
    return out


def _split(
    samples: list[tuple[list[float], int, float]],
    val_ratio: float,
    seed: int,
) -> tuple[list, list]:
    rng = random.Random(seed)
    idx = list(range(len(samples)))
    rng.shuffle(idx)
    n_val = int(len(idx) * val_ratio)
    val_idx = set(idx[:n_val])
    train = [samples[i] for i in idx[n_val:]]
    val = [samples[i] for i in idx[:n_val]]
    return train, val


# --------------------------------------------------------------------------- #
# 训练
# --------------------------------------------------------------------------- #
def train(
    train_samples: list[tuple[list[float], int, float]],
    val_samples: list[tuple[list[float], int, float]],
    epochs: int,
    lr: float,
    seed: int,
) -> tuple[Any, list[float], list[float]]:
    torch, nn = _import_torch()
    RoutingMLP = _import_routing_mlp()
    torch.manual_seed(seed)

    model = RoutingMLP()
    optimizer = torch.optim.Adam(model.parameters(), lr=lr)
    criterion = nn.CrossEntropyLoss()

    if not train_samples:
        print("ERROR: 训练集为空", file=sys.stderr)
        sys.exit(1)

    X_train = torch.tensor([s[0] for s in train_samples], dtype=torch.float32)
    y_train = torch.tensor([s[1] for s in train_samples], dtype=torch.long)
    w_train = torch.tensor([s[2] for s in train_samples], dtype=torch.float32)

    X_val = (
        torch.tensor([s[0] for s in val_samples], dtype=torch.float32)
        if val_samples
        else None
    )
    y_val = (
        torch.tensor([s[1] for s in val_samples], dtype=torch.long)
        if val_samples
        else None
    )

    train_losses: list[float] = []
    val_accs: list[float] = []

    for epoch in range(1, epochs + 1):
        model.train()
        optimizer.zero_grad()
        logits = model(X_train)
        # 带样本权重的交叉熵：手动加权
        losses = nn.functional.cross_entropy(logits, y_train, reduction="none")
        loss = (losses * w_train).sum() / w_train.sum()
        loss.backward()
        optimizer.step()
        train_losses.append(float(loss.item()))

        if X_val is not None:
            model.eval()
            with torch.no_grad():
                val_logits = model(X_val)
                preds = val_logits.argmax(dim=1)
                acc = float((preds == y_val).float().mean().item())
            val_accs.append(acc)
        else:
            val_accs.append(0.0)

        if epoch % 10 == 0 or epoch == 1 or epoch == epochs:
            acc_str = f"{val_accs[-1]:.4f}" if val_samples else "n/a"
            print(f"[train] epoch {epoch:>3}/{epochs}  loss={loss.item():.4f}  val_acc={acc_str}")

    return model, train_losses, val_accs


# --------------------------------------------------------------------------- #
# 产物保存
# --------------------------------------------------------------------------- #
def _next_version(manifest: dict[str, Any]) -> int:
    versions: list[int] = []
    for p in manifest.get("policies") or []:
        try:
            versions.append(int(p.get("version", 0)))
        except (TypeError, ValueError):
            continue
    return (max(versions) + 1) if versions else 1


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def save_policy(
    model: Any,
    manifest_path: Path,
    train_losses: list[float],
    val_accs: list[float],
    train_size: int,
    val_size: int,
    make_active: bool,
) -> dict[str, Any]:
    torch, _ = _import_torch()
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            manifest = {}
    else:
        manifest = {}
    manifest.setdefault("policies", [])

    version = _next_version(manifest)
    weights_path = manifest_path.parent / f"policy_v{version}.pt"
    torch.save(model.state_dict(), weights_path)
    sha = _sha256_file(weights_path)

    entry = {
        "version": str(version),
        "path": weights_path.name,
        "sha256": sha,
        "trained_at": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime()),
        "metrics": {
            "train_size": train_size,
            "val_size": val_size,
            "final_train_loss": train_losses[-1] if train_losses else None,
            "final_val_acc": val_accs[-1] if val_accs else None,
            "epochs": len(train_losses),
        },
    }
    manifest["policies"].append(entry)
    if make_active:
        manifest["active_version"] = str(version)

    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return entry


# --------------------------------------------------------------------------- #
# 报告
# --------------------------------------------------------------------------- #
def render_report(
    entry: dict[str, Any],
    train_losses: list[float],
    val_accs: list[float],
    train_size: int,
    val_size: int,
    total_size: int,
) -> str:
    lines: list[str] = []
    lines.append("=" * 60)
    lines.append("NeuroBus Routing Policy 训练报告")
    lines.append("=" * 60)
    lines.append(f"版本：v{entry['version']}")
    lines.append(f"权重文件：{entry['path']}")
    lines.append(f"sha256：{entry['sha256']}")
    lines.append(f"训练时间：{entry['trained_at']}")
    lines.append(f"总样本：{total_size}（train={train_size}, val={val_size}）")
    lines.append("")
    lines.append("【Loss 曲线（每 5 epoch 采样）】")
    sample_idx = list(range(0, len(train_losses), max(1, len(train_losses) // 10)))
    if sample_idx and sample_idx[-1] != len(train_losses) - 1:
        sample_idx.append(len(train_losses) - 1)
    for i in sample_idx:
        loss = train_losses[i]
        acc = val_accs[i] if i < len(val_accs) else 0.0
        lines.append(f"  epoch {i + 1:>3}  loss={loss:.4f}  val_acc={acc:.4f}")
    lines.append("")
    if val_accs:
        lines.append(
            f"最终验证准确率：{val_accs[-1]:.4f}"
            f"（最高 {max(val_accs):.4f} @ epoch {val_accs.index(max(val_accs)) + 1}）"
        )
    else:
        lines.append("（无验证集）")
    lines.append("=" * 60)
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="训练 NeuroBus 路由策略 MLP（16→32→3）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--labeled", type=Path, default=DEFAULT_LABELED, help="labeled_data.jsonl 路径")
    parser.add_argument(
        "--arbitrated", type=Path, default=DEFAULT_ARBITRATED, help="arbitrated_data.jsonl 路径"
    )
    parser.add_argument("--epochs", type=int, default=50, help="训练轮数（默认 50）")
    parser.add_argument("--lr", type=float, default=0.001, help="Adam 学习率（默认 0.001）")
    parser.add_argument("--val-ratio", type=float, default=0.2, help="验证集比例（默认 0.2）")
    parser.add_argument("--seed", type=int, default=42, help="随机种子（默认 42）")
    parser.add_argument(
        "--manifest", type=Path, default=MANIFEST_PATH, help="manifest.json 路径"
    )
    parser.add_argument(
        "--no-activate",
        action="store_true",
        help="训练后不切换 active_version（仅写入新版本）",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help="训练报告输出路径（默认仅 stdout）",
    )
    args = parser.parse_args(argv)

    labeled = _load_labeled(args.labeled)
    arbitrated = _load_arbitrated(args.arbitrated)
    total_labeled = len(labeled)
    total_arb = len(arbitrated)
    print(
        f"[train] 加载 labeled={total_labeled}（gold+silver），"
        f"arbitrated={total_arb}（accepted）"
    )

    samples = labeled + arbitrated
    if not samples:
        print(
            f"ERROR: 无可用训练样本（labeled={args.labeled}, arbitrated={args.arbitrated}）",
            file=sys.stderr,
        )
        return 1

    train_samples, val_samples = _split(samples, args.val_ratio, args.seed)
    print(
        f"[train] split: train={len(train_samples)} val={len(val_samples)} "
        f"(val_ratio={args.val_ratio})"
    )

    model, train_losses, val_accs = train(
        train_samples, val_samples, args.epochs, args.lr, args.seed
    )

    entry = save_policy(
        model,
        args.manifest,
        train_losses,
        val_accs,
        len(train_samples),
        len(val_samples),
        make_active=not args.no_activate,
    )

    report = render_report(
        entry,
        train_losses,
        val_accs,
        len(train_samples),
        len(val_samples),
        len(samples),
    )
    print(report)
    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(report + "\n", encoding="utf-8")
        print(f"\n[train] 报告已写入 {args.report}", file=sys.stderr)

    active_note = (
        f"active_version → v{entry['version']}"
        if not args.no_activate
        else "active_version 未切换（--no-activate）"
    )
    print(f"[train] 完成：{active_note}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
