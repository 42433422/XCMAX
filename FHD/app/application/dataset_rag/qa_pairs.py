"""问答对（FAQ 模式）归一化与检索块构造。

数据模型对齐 Dify / FastGPT 的问答对知识库：每对由「问题 + 答案」组成，
问题参与召回，答案作为可直接引用的证据。这里只做产品侧薄封装，CSV/JSON
解析与长度、数量边界交给标准库和调用方（pydantic）处理。
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from typing import Any

from app.infrastructure.rag import RetrievedChunk

MAX_QA_PAIRS = 2000
MAX_QUESTION_CHARS = 500
MAX_ANSWER_CHARS = 5000

_QUESTION_KEYS = ("question", "q", "问题")
_ANSWER_KEYS = ("answer", "a", "答案")
_HEADER_QUESTIONS = frozenset({"question", "q", "问题", "questions"})
_HEADER_ANSWERS = frozenset({"answer", "a", "答案", "answers"})


def normalize_qa_pairs(raw: Any) -> list[dict[str, str]]:
    """把列表、JSON 文本或 CSV/TSV 文本归一化为问答对列表。

    非法输入抛 ``ValueError``；空列表表示清空，不视为错误。
    """
    rows = _coerce_rows(raw)
    pairs: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for question, answer in rows:
        question = str(question or "").strip()[:MAX_QUESTION_CHARS]
        answer = str(answer or "").strip()[:MAX_ANSWER_CHARS]
        if not question or not answer:
            continue
        key = (question.casefold(), answer.casefold())
        if key in seen:
            continue
        seen.add(key)
        pairs.append(
            {
                "qa_id": "qa_" + hashlib.sha1(f"{question}\x00{answer}".encode()).hexdigest()[:12],
                "question": question,
                "answer": answer,
            }
        )
        if len(pairs) >= MAX_QA_PAIRS:
            break
    return pairs


def qa_chunks(pairs: list[dict[str, Any]], *, tenant_id: str = "") -> list[RetrievedChunk]:
    """把问答对转成与文档块同形的检索候选，复用混合召回、精排与引用链路。"""
    chunks: list[RetrievedChunk] = []
    for index, pair in enumerate(pairs):
        question = str(pair.get("question") or "").strip()
        answer = str(pair.get("answer") or "").strip()
        if not question or not answer:
            continue
        text = f"问题：{question}\n答案：{answer}"
        chunks.append(
            RetrievedChunk(
                text=text,
                score=0.0,
                source="问答对",
                chunk_index=index,
                char_start=0,
                char_end=len(text),
                metadata={
                    "type": "qa",
                    "qa_id": str(pair.get("qa_id") or ""),
                    "question": question,
                    "tenant_id": tenant_id,
                },
            )
        )
    return chunks


def scoped_qa_pairs(index: dict[str, Any] | None, tenant_id: str) -> list[dict[str, Any]]:
    """只返回当前租户的问答对；空租户表示未启用多租户。"""
    rows = (index or {}).get("qa_pairs")
    if not isinstance(rows, list):
        return []
    return [
        dict(row)
        for row in rows
        if isinstance(row, dict) and str(row.get("tenant_id") or "") == tenant_id
    ]


def _coerce_rows(raw: Any) -> list[tuple[Any, Any]]:
    if raw is None:
        return []
    if isinstance(raw, str):
        return _rows_from_text(raw)
    if isinstance(raw, dict):
        return _rows_from_dicts([raw])
    if isinstance(raw, (list, tuple)):
        if all(isinstance(item, dict) for item in raw):
            return _rows_from_dicts(list(raw))
        return _rows_from_sequences(list(raw))
    raise ValueError("qa pairs must be a list, mapping or CSV/TSV text")


def _rows_from_text(text: str) -> list[tuple[Any, Any]]:
    body = text.strip()
    if not body:
        return []
    if body[0] in "[{":
        try:
            return _coerce_rows(json.loads(body))
        except ValueError as exc:
            raise ValueError("qa pairs JSON is not valid") from exc
    delimiter = "\t" if "\t" in body and "," not in body.split("\n", 1)[0] else ","
    rows = [
        row
        for row in csv.reader(io.StringIO(body), delimiter=delimiter)
        if any(str(cell or "").strip() for cell in row)
    ]
    if (
        rows
        and {str(cell or "").strip().lower() for cell in rows[0][:2]}
        <= (_HEADER_QUESTIONS | _HEADER_ANSWERS)
        and len(rows[0]) >= 2
    ):
        rows = rows[1:]
    return [(row[0], row[1]) for row in rows if len(row) >= 2]


def _rows_from_dicts(rows: list[dict[str, Any]]) -> list[tuple[Any, Any]]:
    return [
        (_pick(row, _QUESTION_KEYS), _pick(row, _ANSWER_KEYS))
        for row in rows
        if isinstance(row, dict)
    ]


def _rows_from_sequences(rows: list[Any]) -> list[tuple[Any, Any]]:
    pairs: list[tuple[Any, Any]] = []
    for row in rows:
        if isinstance(row, dict):
            pairs.append((_pick(row, _QUESTION_KEYS), _pick(row, _ANSWER_KEYS)))
        elif isinstance(row, (list, tuple)) and len(row) >= 2:
            pairs.append((row[0], row[1]))
    return pairs


def _pick(row: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = row.get(key)
        if value:
            return str(value)
    return ""
