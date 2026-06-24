"""会议纪要三级派生内核（纯 LLM，不碰 DB，避免循环导入）。

单一真相链由函数签名强制，调用方无法越级：
    raw_transcript ──derive_level1_script──▶ level1_script
    level1_script  ──derive_level2_architecture──▶ level2_architecture
    level2_architecture ──derive_level3_plain──▶ level3_plain

下游函数只接受上游产物作入参，因此「L2 必须来自 L1、L3 必须来自 L2」是类型层面的约束，
而非约定。``generate_all_levels`` 一次跑完三级；任何级别 LLM 不可用 → 整体降级（degraded）。
"""

from __future__ import annotations

import hashlib
import json
import logging
from functools import lru_cache
from typing import Any

from app.infrastructure.llm.invoke import chat_completion_openai_format
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


class MeetingLLMUnavailable(RuntimeError):
    """LLM 未配置或无响应：触发降级（degraded），区别于真正的执行失败（failed）。"""


# ── Prompt 常量 = 代码 SSOT（随模型行为演进，需评审/版本化，故不放 config 热改）────────────

LEVEL1_SYSTEM = (
    "你是资深会议记录整理助手。下面是一段会议的语音转写原文，可能有口语化、错别字、"
    "停顿词、ASR 识别瑕疵、说话人未区分等问题。\n"
    "请把它整理成【剧本式实录】：\n"
    "1. 清洗口水话、语气词、重复与明显的转写错误，但不得增删事实、不得编造未提到的内容；\n"
    "2. 按说话人分段，用「【发言人A】：…」「【发言人B】：…」标注（无法区分时用「【发言人】」）；\n"
    "3. 话题切换处用「── 议题：xxx ──」分隔；\n"
    "4. 保留关键数字、时间、人名、结论的原貌。\n"
    "直接输出整理后的剧本实录正文，不要加前言或解释。"
)

LEVEL2_SYSTEM = (
    "你是结构化总结助手。下面是一份【剧本式会议实录】。\n"
    "请仅依据该实录，生成【架构图式总结】，包含两部分：\n"
    "1. 一个 Mermaid 流程图/思维导图（用 ```mermaid 代码块包裹，flowchart TD 或 mindmap），"
    "把会议的议题 → 决策 → 行动项 → 依赖关系画成结构图；节点文字简短，"
    "避免特殊字符导致语法错误；\n"
    "2. 紧接着一份提纲，分「议题 / 决策 / 行动项（含负责人与时限，若有） / 风险与依赖」四节，用列表。\n"
    "只依据实录内容，不要臆造。先输出 Mermaid 代码块，再输出提纲。"
)

LEVEL3_SYSTEM = (
    "你是「说人话」助手。下面是一份【架构图式总结】（含 Mermaid 架构图与提纲），"
    "对外行人来说太抽象。\n"
    "请把它翻译成大白话：用日常生活里看得见摸得着的事物和比喻，"
    "代替架构图里的抽象节点和术语，讲清楚「这场会到底为了啥、谁要去干啥、卡在哪」。\n"
    "要求：\n"
    "1. 不要再出现 Mermaid 代码或架构图；用平实的口语段落 + 必要的简单清单；\n"
    "2. 多用类比（例如把流程比作做饭/快递/盖房子等），让没参会的人也秒懂；\n"
    "3. 不丢关键决策和行动项。\n"
    "直接输出大白话正文。"
)

# 每级显式给足输出预算，不沿用 chat_completion 的 2000 默认
_LEVEL1_MAX_TOKENS = 4000
_LEVEL2_MAX_TOKENS = 2500
_LEVEL3_MAX_TOKENS = 2500


def compute_source_hash(raw: str) -> str:
    """原文指纹：sha256(raw_transcript)，用于下游陈旧检测。"""
    return hashlib.sha256((raw or "").encode("utf-8")).hexdigest()


async def _generate_level(system_prompt: str, source_text: str, *, max_tokens: int) -> str:
    """调一次 LLM 生成某一级。LLM 未配置/无响应 → MeetingLLMUnavailable。"""
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": source_text},
    ]
    resp = await chat_completion_openai_format(
        messages, temperature=0.3, max_tokens=max_tokens, profile="default"
    )
    if not resp or not resp.get("choices"):
        raise MeetingLLMUnavailable("LLM 未配置或无响应")
    content = (resp["choices"][0].get("message", {}) or {}).get("content") or ""
    content = content.strip()
    if not content:
        raise MeetingLLMUnavailable("LLM 返回空内容")
    return content


async def derive_level1_script(raw_transcript: str) -> str:
    """第一级 剧本式实录 ← 原文（真相源）。"""
    return await _generate_level(LEVEL1_SYSTEM, raw_transcript, max_tokens=_LEVEL1_MAX_TOKENS)


async def derive_level2_architecture(level1_script: str) -> str:
    """第二级 架构图式总结 ← 第一级剧本（绝不读 raw）。"""
    return await _generate_level(LEVEL2_SYSTEM, level1_script, max_tokens=_LEVEL2_MAX_TOKENS)


async def derive_level3_plain(level2_architecture: str) -> str:
    """第三级 说人话 ← 第二级架构图（绝不读 L1/raw）。"""
    return await _generate_level(LEVEL3_SYSTEM, level2_architecture, max_tokens=_LEVEL3_MAX_TOKENS)


async def generate_all_levels(raw_transcript: str) -> dict[str, Any]:
    """编排：L1←raw、L2←L1、L3←L2，一次跑完。

    Returns:
        dict: ``{status, level1_script, level2_architecture, level3_plain, error_message}``。
        - status=completed：三级齐全。
        - status=degraded：LLM 不可用（MeetingLLMUnavailable），三级为 None。
        - status=failed：可恢复执行错误，三级为 None。
    """
    raw = (raw_transcript or "").strip()
    if not raw:
        return {
            "status": "failed",
            "level1_script": None,
            "level2_architecture": None,
            "level3_plain": None,
            "error_message": "会议原文为空",
        }
    try:
        level1 = await derive_level1_script(raw)
        level2 = await derive_level2_architecture(level1)  # 派生自 L1，绝不读 raw
        level3 = await derive_level3_plain(level2)  # 派生自 L2，绝不读 L1/raw
        return {
            "status": "completed",
            "level1_script": level1,
            "level2_architecture": level2,
            "level3_plain": level3,
            "error_message": None,
        }
    except MeetingLLMUnavailable as exc:
        logger.warning("会议纪要生成降级（LLM 不可用）：%s", exc)
        return {
            "status": "degraded",
            "level1_script": None,
            "level2_architecture": None,
            "level3_plain": None,
            "error_message": str(exc),
        }
    except RECOVERABLE_ERRORS as exc:
        logger.error("会议纪要生成失败：%s", exc, exc_info=True)
        return {
            "status": "failed",
            "level1_script": None,
            "level2_architecture": None,
            "level3_plain": None,
            "error_message": str(exc),
        }


# ── 三级定义 config SSOT（标签/派生关系，前后端共读）──────────────────────────

_FALLBACK_LEVELS = {
    "version": 1,
    "levels": [
        {"id": "level1_script", "label": "剧本式实录", "short": "剧本", "derives_from": "raw"},
        {
            "id": "level2_architecture",
            "label": "架构图式总结",
            "short": "架构图",
            "derives_from": "level1_script",
            "render": "mermaid",
        },
        {
            "id": "level3_plain",
            "label": "说人话",
            "short": "说人话",
            "derives_from": "level2_architecture",
        },
    ],
}


@lru_cache(maxsize=1)
def load_levels_config() -> dict[str, Any]:
    """加载 config/meeting_minutes_levels.json；缺失/异常时回退内置兜底。"""
    try:
        from app.mod_sdk.host_profile import resolve_fhd_config_dir

        cfg = resolve_fhd_config_dir()
        if cfg is not None:
            path = cfg / "meeting_minutes_levels.json"
            if path.is_file():
                doc = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(doc, dict) and isinstance(doc.get("levels"), list):
                    return doc
    except RECOVERABLE_ERRORS as exc:
        logger.warning("加载会议纪要三级定义失败，使用内置兜底：%s", exc)
    return _FALLBACK_LEVELS
