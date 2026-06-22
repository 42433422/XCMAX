#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LLM-D 仲裁：对 disputed 样本用 MiniMax-M3 仲裁，并与规则路由交叉验证。

读取 ``labeled_data.jsonl`` 中的 ``disputed`` 样本，调用 LLM-D（MiniMax-M3，
通过 B.AI 网关 ``BAI_API_KEY``）仲裁。仲裁结果作为 ground truth。

规则路由交叉验证：
- 对比 LLM-D 仲裁与历史规则路由（``history_action`` 字段）
- 一致率 ≥ ``--threshold``（默认 0.7）→ 仲裁可信，disputed 全部采纳
- 一致率 < ``--threshold`` → 仲裁偏离规则，disputed 样本丢弃

输出 ``arbitrated_data.jsonl``，每行::

    {
      "features": [...],
      "label": "reflex|subconscious|conscious",
      "source": "llm_d_arbitration",
      "arbitration_reason": "...",
      "history_action": "...",
      "agree_with_rule": true|false,
      "rule_agreement_rate": 0.0-1.0,
      "accepted": true|false
    }

用法::

    python scripts/dev/llm_label_arbitrate.py --help
    python scripts/dev/llm_label_arbitrate.py \\
        --input resources/routing_policies/labeled_data.jsonl \\
        --output resources/routing_policies/arbitrated_data.jsonl \\
        --threshold 0.7 --concurrency 4
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

try:
    import httpx
except ImportError:  # pragma: no cover
    httpx = None  # type: ignore[assignment]

FHD_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT = FHD_ROOT / "resources" / "routing_policies" / "labeled_data.jsonl"
DEFAULT_OUTPUT = FHD_ROOT / "resources" / "routing_policies" / "arbitrated_data.jsonl"

PROCESSORS = ("reflex", "subconscious", "conscious")
ACTION_TO_PROCESSOR = {
    "reflex": "reflex",
    "subconscious": "subconscious",
    "conscious": "conscious",
    # 兼容历史 action 字段可能的别名
    "0": "reflex",
    "1": "subconscious",
    "2": "conscious",
}

logger = logging.getLogger("llm_label_arbitrate")

# B.AI OpenAI 兼容 API（仲裁用 minimax-m3）
BAI_BASE_URL = "https://api.b.ai/v1/chat/completions"
ARBITRATION_MODEL = "minimax-m3"


def _api_key() -> str:
    return (os.environ.get("BAI_API_KEY") or "").strip()


PROMPT_SYSTEM = (
    "你是 NeuroBus 路由仲裁器。三个 LLM 标注员对同一条样本给出了不同的处理器判断，"
    "请你基于特征与历史路由信息做出最终仲裁。\n"
    "处理器定义：\n"
    "- reflex：反射级（<1ms），简单问候/确认/紧急停止/纯命令式短输入\n"
    "- subconscious：潜意识级（<10ms），状态查询/帮助/常见 FAQ\n"
    "- conscious：显意识级（<200ms），复杂推理/多轮对话/需要 LLM 生成\n"
    "只输出 JSON：{\"processor\": \"reflex|subconscious|conscious\", "
    "\"reason\": \"<=50字\", \"confidence\": 0.0-1.0}"
)


def _features_summary(features: list[float]) -> str:
    feat = features or []
    pad = feat + [0.0] * max(0, 16 - len(feat))
    parts = [
        f"len_norm={pad[0]:.2f}",
        f"newline_norm={pad[1]:.2f}",
        f"question_norm={pad[2]:.2f}",
        f"cn_biz_kw={pad[3]:.0f}",
        f"en_biz_kw={pad[4]:.0f}",
        f"priority={pad[5]:.2f}",
        f"intent_conf={pad[6]:.2f}",
        f"session_depth={pad[7]:.2f}",
        f"digit_ratio={pad[8]:.2f}",
        f"slash_cmd={pad[9]:.0f}",
        f"len_sin={pad[10]:.2f}",
        f"len_cos={pad[11]:.2f}",
        f"utf8_bytes={pad[12]:.2f}",
        f"user_override={pad[13]:.0f}",
        f"system_overload={pad[14]:.0f}",
        f"has_event={pad[15]:.0f}",
    ]
    return ", ".join(parts)


def _build_messages(row: dict[str, Any]) -> list[dict[str, str]]:
    features = list(row.get("features") or [])
    labels = row.get("labels") or {}
    label_lines = []
    for provider in ("minimax", "glm", "kimi", "gpt"):
        v = labels.get(provider)
        if v is None:
            continue
        label_lines.append(
            f"- {provider}: processor={v.get('processor')}, "
            f"confidence={v.get('confidence')}, reason={v.get('reason','')}"
        )
    labels_block = "\n".join(label_lines) or "- (无可用标注)"
    history = row.get("history_action") or "(无)"
    user = (
        "请对以下 NeuroBus 路由样本做最终仲裁。\n\n"
        f"特征摘要：\n{_features_summary(features)}\n\n"
        f"历史规则路由 action：{history}\n\n"
        f"三个 LLM 标注员的判断：\n{labels_block}\n\n"
        "请输出 JSON。"
    )
    return [
        {"role": "user", "content": PROMPT_SYSTEM + "\n\n" + user},
    ]


def _parse_arbitration(content: str) -> dict[str, Any] | None:
    text = (content or "").strip()
    if not text:
        return None
    # 去除 minimax-m3 的 <think>...</think> 推理标签
    if "<think>" in text and "</think>" in text:
        think_start = text.find("<think>")
        think_end = text.find("</think>") + len("</think>")
        text = (text[:think_start] + text[think_end:]).strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        try:
            obj = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None
    proc = str(obj.get("processor", "")).strip().lower()
    if proc not in PROCESSORS:
        return None
    try:
        conf = float(obj.get("confidence", 0.5))
    except (TypeError, ValueError):
        conf = 0.5
    conf = max(0.0, min(1.0, conf))
    return {
        "processor": proc,
        "reason": str(obj.get("reason", ""))[:200],
        "confidence": conf,
    }


async def _call_arbitrator(
    client: "httpx.AsyncClient",
    row: dict[str, Any],
    timeout: float,
) -> dict[str, Any] | None:
    api_key = _api_key()
    if not api_key:
        logger.warning("未配置 BAI_API_KEY，跳过仲裁。")
        return None
    payload = {
        "model": ARBITRATION_MODEL,
        "max_tokens": 2000,
        "temperature": 0.0,
        "messages": _build_messages(row),
        "reasoning_split": True,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    try:
        resp = await client.post(BAI_BASE_URL, json=payload, headers=headers, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
    except (httpx.ConnectError, httpx.ReadError, httpx.ReadTimeout, httpx.RemoteProtocolError) as e:
        # 网络瞬时错误：重试 1 次（minimax-m3 偶发断连）
        logger.warning("B.AI 仲裁网络错误，重试：%s", e)
        try:
            await asyncio.sleep(1.0)
            resp = await client.post(BAI_BASE_URL, json=payload, headers=headers, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e2:  # noqa: BLE001
            logger.warning("B.AI 仲裁重试仍失败：%s", e2)
            return None
    except Exception as e:  # noqa: BLE001
        logger.warning("B.AI 仲裁调用失败：%s", e)
        return None
    try:
        content = data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        logger.warning("B.AI 响应结构异常：%s", data)
        return None
    return _parse_arbitration(content)


def _normalize_action(action: Any) -> str:
    if action is None:
        return ""
    s = str(action).strip().lower()
    return ACTION_TO_PROCESSOR.get(s, s)


def _load_disputed(input_path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with input_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if obj.get("consensus") == "disputed":
                rows.append(obj)
    return rows


async def run_arbitration(args: argparse.Namespace) -> int:
    if httpx is None:
        print("ERROR: 缺 httpx 依赖（pip install httpx）", file=sys.stderr)
        return 1
    input_path = Path(args.input)
    if not input_path.is_file():
        print(f"ERROR: 输入文件不存在：{input_path}", file=sys.stderr)
        return 1
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    disputed = _load_disputed(input_path)
    total = len(disputed)
    print(f"[arbitrate] disputed 样本 {total} 条")

    if total == 0:
        # 仍写出空文件，便于下游脚本统一处理
        output_path.write_text("", encoding="utf-8")
        print("[arbitrate] 无 disputed 样本，输出空文件。")
        return 0

    if not _api_key():
        print(
            "[arbitrate] 未配置 BAI_API_KEY；所有 disputed 样本将标记为 accepted=false。",
            file=sys.stderr,
        )

    sem = asyncio.Semaphore(max(1, args.concurrency))

    async with httpx.AsyncClient() as client:
        async def _bounded(row: dict[str, Any]) -> dict[str, Any] | None:
            async with sem:
                return await _call_arbitrator(client, row, args.timeout)

        tasks = [_bounded(r) for r in disputed]
        results = await asyncio.gather(*tasks, return_exceptions=False)

    # 计算规则一致率（仅对成功仲裁的样本）
    arbitrated_rows: list[dict[str, Any]] = []
    agree_count = 0
    arbitrated_count = 0
    for row, arb in zip(disputed, results):
        history_action = _normalize_action(row.get("history_action"))
        if arb is None:
            arbitrated_rows.append(
                {
                    "features": list(row.get("features") or []),
                    "label": "",
                    "source": "llm_d_arbitration",
                    "arbitration_reason": "arbitration_unavailable",
                    "history_action": row.get("history_action"),
                    "agree_with_rule": False,
                    "rule_agreement_rate": 0.0,
                    "accepted": False,
                    "arbitrated_at": time.time(),
                }
            )
            continue
        arbitrated_count += 1
        agree = bool(history_action) and arb["processor"] == history_action
        if agree:
            agree_count += 1
        arbitrated_rows.append(
            {
                "features": list(row.get("features") or []),
                "label": arb["processor"],
                "source": "llm_d_arbitration",
                "arbitration_reason": arb["reason"],
                "arbitration_confidence": arb["confidence"],
                "history_action": row.get("history_action"),
                "agree_with_rule": agree,
                "rule_agreement_rate": 0.0,  # 占位，下面统一回填
                "accepted": False,  # 占位，下面统一回填
                "arbitrated_at": time.time(),
            }
        )

    rate = (agree_count / arbitrated_count) if arbitrated_count else 0.0
    accepted = rate >= args.threshold
    print(
        f"[arbitrate] 仲裁成功 {arbitrated_count}/{total}；"
        f"与规则一致 {agree_count}（rate={rate:.2%}）；"
        f"阈值 {args.threshold:.0%} → {'采纳' if accepted else '丢弃'}"
    )

    with output_path.open("w", encoding="utf-8") as out:
        for r in arbitrated_rows:
            if not r.get("label"):
                r["rule_agreement_rate"] = rate
                r["accepted"] = False
            else:
                r["rule_agreement_rate"] = rate
                r["accepted"] = accepted
            out.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"[arbitrate] 完成：写入 {len(arbitrated_rows)} 条 → {output_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="LLM-D 仲裁：对 disputed 样本用 Claude-Sonnet 仲裁",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="labeled_data.jsonl 路径")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="输出 arbitrated_data.jsonl 路径")
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.7,
        help="规则一致率阈值（默认 0.7）；低于此值则丢弃 disputed 样本",
    )
    parser.add_argument(
        "--concurrency", type=int, default=4, help="并发调用 LLM-D 的样本数（默认 4）"
    )
    parser.add_argument(
        "--timeout", type=float, default=30.0, help="单次 LLM-D 调用超时秒数（默认 30）"
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        help="日志级别",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    return asyncio.run(run_arbitration(args))


if __name__ == "__main__":
    sys.exit(main())
