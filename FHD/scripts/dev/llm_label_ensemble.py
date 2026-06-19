#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LLM 交叉评审标注：4 模型盲标 + 一致性分级。

读取 ``routing_decisions.jsonl``（或指定输入文件），对每条样本用 4 个 LLM
（MiniMax-M3 / GLM-5.2 / Kimi-K2.5 / GPT-5.5）独立标注，输出 ``labeled_data.jsonl``。

所有模型通过 B.AI 网关（https://api.b.ai/v1）调用，OpenAI 兼容格式。

一致性分级（4 模型）：
- 4/4 一致 → ``gold``
- 3/4 一致 → ``silver``（多数派标签作为 ``label``）
- 2/4 或更低 → ``disputed``（``label`` 留空，交由仲裁脚本处理）

每个模型输出::

    {"processor": "reflex|subconscious|conscious", "reason": "...", "confidence": 0.0-1.0}

API key 通过环境变量配置：
- ``BAI_API_KEY`` → B.AI 网关密钥（所有模型共用）

未配置 key 时所有模型跳过，样本仍写入输出文件但 labels 全为 null。

用法::

    python scripts/dev/llm_label_ensemble.py --help
    python scripts/dev/llm_label_ensemble.py \\
        --input resources/routing_policies/routing_decisions.jsonl \\
        --output resources/routing_policies/labeled_data.jsonl \\
        --limit 100 --concurrency 4
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
DEFAULT_INPUT = FHD_ROOT / "resources" / "routing_policies" / "routing_decisions.jsonl"
DEFAULT_OUTPUT = FHD_ROOT / "resources" / "routing_policies" / "labeled_data.jsonl"

PROCESSORS = ("reflex", "subconscious", "conscious")
PROCESSOR_TO_IDX = {"reflex": 0, "subconscious": 1, "conscious": 2}

logger = logging.getLogger("llm_label_ensemble")

# --------------------------------------------------------------------------- #
# 模型配置（B.AI 网关，OpenAI 兼容，共用 BAI_API_KEY）
# --------------------------------------------------------------------------- #
BAI_BASE_URL = "https://api.b.ai/v1/chat/completions"

MODEL_CONFIGS: dict[str, dict[str, str]] = {
    "minimax": {
        "env_key": "BAI_API_KEY",
        "base_url": BAI_BASE_URL,
        "model": "minimax-m3",
        "display": "MiniMax-M3",
    },
    "glm": {
        "env_key": "BAI_API_KEY",
        "base_url": BAI_BASE_URL,
        "model": "glm-5.2",
        "display": "GLM-5.2",
    },
    "kimi": {
        "env_key": "BAI_API_KEY",
        "base_url": BAI_BASE_URL,
        "model": "gpt-5.4",
        "display": "GPT-5.4",
    },
    "gpt": {
        "env_key": "BAI_API_KEY",
        "base_url": BAI_BASE_URL,
        "model": "gpt-5.5",
        "display": "GPT-5.5",
    },
}


def _api_key(provider: str) -> str:
    return (os.environ.get(MODEL_CONFIGS[provider]["env_key"]) or "").strip()


def _available_providers() -> list[str]:
    avail: list[str] = []
    for name in ("minimax", "glm", "kimi", "gpt"):
        if _api_key(name):
            avail.append(name)
        else:
            logger.warning(
                "跳过模型 %s（%s）：未配置 %s",
                MODEL_CONFIGS[name]["display"],
                name,
                MODEL_CONFIGS[name]["env_key"],
            )
    return avail


# --------------------------------------------------------------------------- #
# Prompt 构造
# --------------------------------------------------------------------------- #
PROMPT_SYSTEM = (
    "你是 NeuroBus 路由分类器。给定一条用户请求的特征向量与历史路由信息，"
    "判断该请求应当由哪个处理器处理。\n"
    "处理器定义：\n"
    "- reflex：反射级（<1ms），简单问候/确认/紧急停止/纯命令式短输入\n"
    "- subconscious：潜意识级（<10ms），状态查询/帮助/常见 FAQ\n"
    "- conscious：显意识级（<200ms），复杂推理/多轮对话/需要 LLM 生成\n"
    "只输出 JSON：{\"processor\": \"reflex|subconscious|conscious\", "
    "\"reason\": \"<=50字\", \"confidence\": 0.0-1.0}"
)


def _features_summary(features: list[float], row: dict[str, Any]) -> str:
    """把 16 维特征与历史路由信息压缩成 LLM 可读摘要。"""
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
    summary = ", ".join(parts)
    action = row.get("action") or ""
    latency = row.get("latency_ms")
    sla_hit = row.get("sla_hit")
    success = row.get("success")
    if action:
        summary += f"\n历史路由 action={action}"
    if latency is not None:
        summary += f", latency_ms={latency}"
    if sla_hit is not None:
        summary += f", sla_hit={sla_hit}"
    if success is not None:
        summary += f", success={success}"
    return summary


def _build_messages(features: list[float], row: dict[str, Any]) -> list[dict[str, str]]:
    user = (
        "请对以下 NeuroBus 路由样本分类。\n\n"
        f"特征摘要：\n{_features_summary(features, row)}\n\n"
        "请输出 JSON。"
    )
    return [
        {"role": "system", "content": PROMPT_SYSTEM},
        {"role": "user", "content": user},
    ]


# --------------------------------------------------------------------------- #
# 单模型调用
# --------------------------------------------------------------------------- #
async def _call_model(
    client: "httpx.AsyncClient",
    provider: str,
    features: list[float],
    row: dict[str, Any],
    timeout: float,
) -> dict[str, Any] | None:
    cfg = MODEL_CONFIGS[provider]
    api_key = _api_key(provider)
    if not api_key:
        return None
    payload = {
        "model": cfg["model"],
        "messages": _build_messages(features, row),
        "temperature": 0.0,
        "max_tokens": 2000,  # minimax-m3 推理需要大量 token
    }
    # minimax-m3 支持分离推理内容，避免 <think> 耗尽 max_tokens
    if provider == "minimax":
        payload["reasoning_split"] = True
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    try:
        resp = await client.post(
            cfg["base_url"], json=payload, headers=headers, timeout=timeout
        )
        resp.raise_for_status()
        data = resp.json()
    except (httpx.ConnectError, httpx.ReadError, httpx.ReadTimeout, httpx.RemoteProtocolError) as e:
        # 网络瞬时错误：重试 1 次（minimax-m3 偶发断连）
        logger.warning("模型 %s 网络错误，重试：%s", cfg["display"], e)
        try:
            await asyncio.sleep(1.0)
            resp = await client.post(
                cfg["base_url"], json=payload, headers=headers, timeout=timeout
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e2:  # noqa: BLE001
            logger.warning("模型 %s 重试仍失败：%s", cfg["display"], e2)
            return None
    except Exception as e:  # noqa: BLE001
        logger.warning("模型 %s 调用失败：%s", cfg["display"], e)
        return None
    content = ""
    try:
        content = data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        logger.warning("模型 %s 响应结构异常：%s", cfg["display"], data)
        return None
    return _parse_model_output(content, provider)


def _parse_model_output(content: str, provider: str) -> dict[str, Any] | None:
    """从 LLM 文本中抽取 JSON。容忍 <think> 标签、前后多余文字、```json 代码块。"""
    text = (content or "").strip()
    if not text:
        return None
    # 去除 minimax-m3 等模型的 <think>...</think> 推理标签
    if "<think>" in text and "</think>" in text:
        think_start = text.find("<think>")
        think_end = text.find("</think>") + len("</think>")
        text = (text[:think_start] + text[think_end:]).strip()
    # 去除 markdown 代码块
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    # 直接解析
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        # 截取第一个 {...} 段
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            logger.warning("模型 %s 输出无法解析为 JSON：%r", provider, content)
            return None
        try:
            obj = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            logger.warning("模型 %s 输出 JSON 解析失败：%r", provider, content)
            return None
    proc = str(obj.get("processor", "")).strip().lower()
    if proc not in PROCESSORS:
        logger.warning("模型 %s processor 非法：%r", provider, proc)
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


# --------------------------------------------------------------------------- #
# 一致性分级
# --------------------------------------------------------------------------- #
def _grade_consensus(labels: dict[str, dict[str, Any] | None]) -> tuple[str, str]:
    """返回 (consensus, label)。label 为多数派 processor 或空串。

    4 模型分级：
    - 4/4 一致 → gold
    - 3/4 一致 → silver
    - 2/4 或更低 → disputed
    """
    valid = [v for v in labels.values() if v is not None]
    if not valid:
        return "disputed", ""
    counts: dict[str, int] = {}
    for v in valid:
        counts[v["processor"]] = counts.get(v["processor"], 0) + 1
    max_count = max(counts.values())
    total_valid = len(valid)
    # 4/4 或 3/4 一致
    if max_count >= 3:
        label = next(p for p, c in counts.items() if c == max_count)
        return ("gold" if max_count == total_valid else "silver"), label
    return "disputed", ""


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
async def label_row(
    client: "httpx.AsyncClient",
    providers: list[str],
    row: dict[str, Any],
    timeout: float,
) -> dict[str, Any]:
    features = list(row.get("features") or [])
    tasks = [_call_model(client, p, features, row, timeout) for p in providers]
    results = await asyncio.gather(*tasks, return_exceptions=False)
    labels = {p: r for p, r in zip(providers, results)}
    consensus, label = _grade_consensus(labels)
    return {
        "ts": row.get("ts"),
        "trace_id": row.get("trace_id"),
        "features": features,
        "history_action": row.get("action"),
        "latency_ms": row.get("latency_ms"),
        "sla_hit": row.get("sla_hit"),
        "success": row.get("success"),
        "labels": labels,
        "consensus": consensus,
        "label": label,
        "labeled_at": time.time(),
    }


async def run_labeling(args: argparse.Namespace) -> int:
    if httpx is None:
        print("ERROR: 缺 httpx 依赖（pip install httpx）", file=sys.stderr)
        return 1
    input_path = Path(args.input)
    if not input_path.is_file():
        print(f"ERROR: 输入文件不存在：{input_path}", file=sys.stderr)
        return 1
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    providers = _available_providers()
    if not providers:
        logger.warning("无可用 LLM 提供商；样本仍会写入，但 labels 全为 null。")

    # 读取输入
    with input_path.open("r", encoding="utf-8") as f:
        rows = []
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                logger.warning("跳过非法 JSON 行：%r", line[:80])
    if args.limit and args.limit > 0:
        rows = rows[: args.limit]
    total = len(rows)
    print(f"[llm-label] 输入 {total} 条样本；可用模型 {len(providers)} 个：{providers}")

    sem = asyncio.Semaphore(max(1, args.concurrency))

    async with httpx.AsyncClient(timeout=httpx.Timeout(args.timeout * 2, connect=30.0)) as client:
        async def _bounded(idx: int, row: dict[str, Any]) -> tuple[int, dict[str, Any]]:
            async with sem:
                labeled = await label_row(client, providers, row, args.timeout)
                return idx, labeled

        # 真正并发：一次性提交所有任务，由 Semaphore 限制同时在飞的样本数
        tasks = [_bounded(i, row) for i, row in enumerate(rows)]
        written = 0
        done = 0
        with output_path.open("w", encoding="utf-8") as out:
            for fut in asyncio.as_completed(tasks):
                try:
                    idx, labeled = await fut
                except Exception as e:  # noqa: BLE001
                    done += 1
                    logger.warning("样本标注失败：%s", e)
                    continue
                out.write(json.dumps(labeled, ensure_ascii=False) + "\n")
                out.flush()
                written += 1
                done += 1
                if done % 20 == 0 or done == total:
                    print(f"[llm-label] 进度 {done}/{total}（已写入 {written}）", flush=True)

    # 简要统计
    gold = silver = disputed = 0
    with output_path.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            c = obj.get("consensus")
            if c == "gold":
                gold += 1
            elif c == "silver":
                silver += 1
            else:
                disputed += 1
    print(
        f"[llm-label] 完成：写入 {written} 条 → {output_path}\n"
        f"  gold={gold}  silver={silver}  disputed={disputed}"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="LLM 交叉评审标注：3 模型盲标 + 一致性分级",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="输入 jsonl 路径")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="输出 jsonl 路径")
    parser.add_argument("--limit", type=int, default=0, help="只处理前 N 条（0=全部）")
    parser.add_argument(
        "--concurrency", type=int, default=4, help="并发调用 LLM 的样本数（默认 4）"
    )
    parser.add_argument(
        "--timeout", type=float, default=30.0, help="单次 LLM 调用超时秒数（默认 30）"
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
    return asyncio.run(run_labeling(args))


if __name__ == "__main__":
    sys.exit(main())
