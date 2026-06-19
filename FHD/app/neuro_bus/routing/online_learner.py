"""在线微调器 — Contextual Bandit with ε-greedy exploration."""

from __future__ import annotations

import hashlib
import json
import logging
import random
import time
from collections import deque
from pathlib import Path
from typing import Any

from app.neuro_bus.routing.policy_nn import (
    get_policy,
    save_policy_state_dict,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

try:
    import torch
    import torch.nn as nn
except ImportError:  # pragma: no cover
    torch = None  # type: ignore[assignment]
    nn = None  # type: ignore[assignment]


def _manifest_path() -> Path:
    return Path(__file__).resolve().parents[3] / "resources" / "routing_policies" / "manifest.json"


def _policies_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "resources" / "routing_policies"


class OnlineLearner:
    """Contextual Bandit 在线微调器。

    使用 ε-greedy 探索 + 重要性采样修正的 SGD 更新路由策略。
    滑动窗口收集 (features, action, reward) 样本，达到阈值后触发增量更新。

    reward = sla_hit * 0.6 + success * 0.4
    """

    def __init__(
        self,
        window_size: int = 10000,
        epsilon: float = 0.1,
        lr: float = 0.001,
        update_threshold: int = 10000,
    ) -> None:
        self.window_size = window_size
        self.epsilon = epsilon
        self.lr = lr
        self.update_threshold = update_threshold
        # 滑动窗口：每条样本 = (features, action, reward, sla_hit, success)
        self._window: deque[tuple[list[float], int, float, bool, bool]] = deque(
            maxlen=window_size
        )
        self._explore_count = 0
        self._total_count = 0

    def should_explore(self) -> bool:
        """ε-greedy: 以 epsilon 概率探索。"""
        decision = random.random() < self.epsilon
        self._total_count += 1
        if decision:
            self._explore_count += 1
        return decision

    def record_decision(
        self,
        features: list[float],
        action: int,
        reward: float | None = None,
        sla_hit: bool | None = None,
        success: bool | None = None,
    ) -> None:
        """记录一条决策样本到滑动窗口。

        reward 优先使用传入值；未传时按 reward = sla_hit*0.6 + success*0.4 计算。
        """
        sh = bool(sla_hit) if sla_hit is not None else False
        ss = bool(success) if success is not None else False
        if reward is None:
            reward = sh * 0.6 + ss * 0.4
        self._window.append((list(features), int(action), float(reward), sh, ss))

    def should_update(self) -> bool:
        """窗口样本数 >= update_threshold 时触发更新。"""
        return len(self._window) >= self.update_threshold

    def update_policy(self) -> str | None:
        """从滑动窗口采样，off-policy 修正后增量更新策略。

        步骤：
        1. 从窗口采样全部样本
        2. 计算重要性采样权重 IS = 1/π(action|features)（π 用当前 policy 的 softmax 概率）
        3. SGD on reward-weighted CrossEntropyLoss with sample weights
        4. 保存新版本 policy_v{N+1}.pt + 更新 manifest.json
        5. 返回新版本号；失败返回 None

        torch 不可用时优雅降级返回 None。
        """
        if torch is None or nn is None:
            logger.warning("torch not available, skip online update")
            return None

        if len(self._window) == 0:
            logger.info("empty window, skip online update")
            return None

        policy = get_policy()
        if policy is None:
            logger.warning("no active policy loaded, skip online update")
            return None

        try:
            # 1. 准备训练数据
            samples = list(self._window)
            features_list = [s[0] for s in samples]
            actions_list = [s[1] for s in samples]
            rewards_list = [s[2] for s in samples]

            features_tensor = torch.tensor(features_list, dtype=torch.float32)
            actions_tensor = torch.tensor(actions_list, dtype=torch.long)
            rewards_tensor = torch.tensor(rewards_list, dtype=torch.float32)

            # 2. 前向传播（开启 grad 用于 CE loss）
            policy.train()
            logits = policy(features_tensor)

            # 3. 重要性采样权重 IS = 1/π(action|features)（detach，不参与梯度）
            with torch.no_grad():
                probs = torch.softmax(logits, dim=1)
                action_probs = probs.gather(1, actions_tensor.unsqueeze(1)).squeeze(1)
                action_probs = torch.clamp(action_probs, min=1e-6)
                is_weights = 1.0 / action_probs
                # 裁剪防止高方差
                is_weights = torch.clamp(is_weights, max=10.0)
                # 自归一化
                is_weights = is_weights / is_weights.mean()

            # 4. 加权 CrossEntropyLoss（reward-weighted + IS-corrected）
            criterion = nn.CrossEntropyLoss(reduction="none")
            ce_loss = criterion(logits, actions_tensor)
            weighted_loss = (is_weights * rewards_tensor * ce_loss).mean()

            # 5. SGD 更新
            optimizer = torch.optim.SGD(policy.parameters(), lr=self.lr)
            optimizer.zero_grad()
            weighted_loss.backward()
            optimizer.step()

            policy.eval()

            # 6. 保存新版本
            new_version = self._next_version()
            new_path = _policies_dir() / f"policy_v{new_version}.pt"
            save_policy_state_dict(new_path, policy)

            # 7. 更新 manifest
            self._update_manifest(new_version, new_path)

            logger.info(
                "online update done: version=%s, samples=%d, loss=%.4f",
                new_version,
                len(samples),
                float(weighted_loss.item()),
            )
            return new_version
        except RECOVERABLE_ERRORS as e:  # pragma: no cover - 防御性
            logger.error("online update failed: %s", e)
            return None

    def _next_version(self) -> str:
        """从 manifest 读取最大版本号 +1。"""
        try:
            manifest_file = _manifest_path()
            if not manifest_file.is_file():
                return "1"
            manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
            versions = [
                int(p.get("version", "0"))
                for p in manifest.get("policies", [])
                if str(p.get("version", "")).isdigit()
            ]
            max_v = max(versions) if versions else 0
            return str(max_v + 1)
        except RECOVERABLE_ERRORS:
            return "1"

    def _update_manifest(self, version: str, weights_path: Path) -> None:
        """更新 manifest.json：追加新版本，设置 active_version。"""
        manifest_file = _manifest_path()
        try:
            if manifest_file.is_file():
                manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
            else:
                manifest = {"active_version": "0", "policies": []}
        except RECOVERABLE_ERRORS:
            manifest = {"active_version": "0", "policies": []}

        sha256 = self._compute_sha256(weights_path)
        trained_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        new_entry = {
            "version": version,
            "path": f"policy_v{version}.pt",
            "sha256": sha256,
            "trained_at": trained_at,
        }

        # 移除同版本旧条目（幂等）
        manifest["policies"] = [
            p for p in manifest.get("policies", []) if str(p.get("version")) != version
        ]
        manifest["policies"].append(new_entry)
        manifest["active_version"] = version

        manifest_file.parent.mkdir(parents=True, exist_ok=True)
        manifest_file.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    @staticmethod
    def _compute_sha256(path: Path) -> str:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()

    def get_stats(self) -> dict[str, Any]:
        """返回窗口样本数、平均 reward、探索率等统计。"""
        samples = list(self._window)
        if samples:
            rewards = [s[2] for s in samples]
            avg_reward = sum(rewards) / len(rewards)
            sla_hits = sum(1 for s in samples if s[3])
            successes = sum(1 for s in samples if s[4])
        else:
            avg_reward = 0.0
            sla_hits = 0
            successes = 0

        explore_rate = (
            self._explore_count / self._total_count if self._total_count > 0 else 0.0
        )

        return {
            "window_size": len(samples),
            "max_window_size": self.window_size,
            "avg_reward": avg_reward,
            "sla_hit_count": sla_hits,
            "success_count": successes,
            "epsilon": self.epsilon,
            "lr": self.lr,
            "update_threshold": self.update_threshold,
            "explore_count": self._explore_count,
            "total_count": self._total_count,
            "explore_rate": explore_rate,
            "should_update": self.should_update(),
        }
