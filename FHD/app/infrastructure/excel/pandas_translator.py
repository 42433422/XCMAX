"""自然语言 → pandas 代码翻译器。

复用仓库已有能力：统一 LLM 入口（``chat_completion_openai_format``）、同步桥
（``run_coroutine_sync``）、schema 快照（``dataframe_schema_snapshot``）与生成
代码校验（``_validate_generated_code``）。翻译结果再由 ``_safe_exec_pandas``
在受限环境里执行。
"""

from __future__ import annotations

import json
import logging
from typing import Any

import pandas as pd

from app.infrastructure.excel.schema_service import dataframe_schema_snapshot
from app.infrastructure.excel.text_to_pandas import _validate_generated_code
from app.infrastructure.llm.invoke import chat_completion_openai_format
from app.utils.async_runtime import run_coroutine_sync
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

_MAX_SCHEMA_CHARS = 4000
_MAX_SAMPLE_VALUES = 6

_SYSTEM_PROMPT = (
    "你是表格数据分析助手，把用户的中文问题翻译成一段可执行的 Python/pandas 代码。\n"
    "执行环境只提供 df(DataFrame)、pd(pandas)、cn_date(series, default_year=None)、"
    "to_number(series)，没有其他变量。\n"
    "必须遵守：\n"
    "1. 最终结果必须赋值给 result（DataFrame 或 Series）。\n"
    "2. 禁止 import、文件/网络/print 操作，禁止以下划线开头的属性。\n"
    "3. 列名必须与给定列清单完全一致，不要臆造列名。\n"
    "4. 中文日期区间（如 12月27-26年1月23、2月）或 Excel 序列号一律用 cn_date(df['列名']) 取日期。\n"
    "5. 金额文本（带逗号、元、￥）用 to_number(df['列名']) 转数值。\n"
    "6. 只输出代码，不要解释，不要 markdown 代码围栏。"
)


def _schema_payload(df: pd.DataFrame) -> dict[str, Any]:
    snapshot = dataframe_schema_snapshot(df, sample_rows=3)
    sample_values: dict[str, list[str]] = {}
    for name in df.columns:
        column = df[name]
        if column.dtype.kind in "iufbM":
            continue
        values = column.dropna().astype(str).drop_duplicates().head(_MAX_SAMPLE_VALUES)
        if len(values):
            sample_values[str(name)] = [value[:40] for value in values]
    snapshot["sample_values"] = sample_values
    return snapshot


def _user_prompt(natural_language: str, df: pd.DataFrame, error_feedback: str | None) -> str:
    schema = json.dumps(_schema_payload(df), ensure_ascii=False, default=str)[:_MAX_SCHEMA_CHARS]
    prompt = f"表格结构：\n{schema}\n\n用户问题：{natural_language}"
    if error_feedback:
        prompt += (
            "\n\n上一次生成的代码执行失败，请修正后重新输出完整代码。"
            f"\n失败信息：{error_feedback[:1200]}"
        )
    return prompt


def _extract_content(response: dict[str, Any]) -> str:
    choices = response.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        message = choices[0].get("message")
        if isinstance(message, dict):
            return str(message.get("content") or "")
        return str(choices[0].get("text") or "")
    return str(response.get("content") or response.get("text") or "")


def _strip_code_fence(content: str) -> str:
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


class LLMPandasTranslator:
    """把自然语言问题转成受限 pandas 代码；无法翻译时返回 ``None``。"""

    def __init__(self, *, max_tokens: int = 900, temperature: float = 0.0) -> None:
        self.max_tokens = max_tokens
        self.temperature = temperature

    def translate(
        self,
        natural_language: str,
        df: pd.DataFrame,
        *,
        error_feedback: str | None = None,
    ) -> str | None:
        question = str(natural_language or "").strip()
        if not question:
            return None
        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": _user_prompt(question, df, error_feedback)},
        ]
        try:
            response = run_coroutine_sync(
                chat_completion_openai_format(
                    messages,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                    profile="excel_text_to_pandas",
                )
            )
        except RECOVERABLE_ERRORS as exc:
            logger.warning("pandas translation LLM call failed: %s", exc)
            return None
        if not isinstance(response, dict):
            return None
        code = _strip_code_fence(_extract_content(response))
        if not code or code.startswith("{"):
            return None
        validation_error = _validate_generated_code(code)
        if validation_error:
            logger.warning("pandas translation rejected: %s", validation_error)
            return None
        return code


__all__ = ["LLMPandasTranslator"]
