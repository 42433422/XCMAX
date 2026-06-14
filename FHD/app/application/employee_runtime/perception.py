# -*- coding: utf-8 -*-
"""员工感知管线（PerceptionPipeline）。

此前感知层 ``_perception_real`` 原样透传输入；本管线按 ``perception.type`` 真正处理多模态：

- document → SemanticChunker 切块 + HybridRetriever(BM25, 0 依赖) 按任务抽取要点
- image   → 复用 OCRService 识别图像文字
- audio   → 若提供 transcript 则采用，否则声明降级（ASR 可后续接入）
- text    → 透传

输出为 ``_perception_real`` 的超集：保留 ``normalized_input`` + ``type``，并把抽取产物
注入 ``normalized_input["_perception"]`` 供认知层 LLM 消费。全部 best-effort，不抛错。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from app.domain.employee.perception_spec import (
    PERCEPTION_AUDIO,
    PERCEPTION_DOCUMENT,
    PERCEPTION_IMAGE,
    PerceptionSpec,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

_TEXT_EXT = {".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".log", ".yaml", ".yml", ".py", ".html", ".xml", ".rst"}
_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tiff", ".tif", ".webp"}
_AUDIO_EXT = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".aac"}

_MAX_DOC_CHARS = 200_000
_KEYPOINT_TOPK = 5


class PerceptionPipeline:
    def __init__(self, config: dict[str, Any] | None) -> None:
        self.config = config or {}
        self.spec = PerceptionSpec.from_config(self.config)

    def process(self, payload: dict[str, Any] | None) -> dict[str, Any]:
        payload = dict(payload or {})
        file_path = str(payload.get("file_path") or payload.get("path") or "").strip()
        task_hint = str(
            payload.get("user_request") or payload.get("task") or payload.get("query") or ""
        ).strip()
        artifacts: dict[str, Any] = {}

        if self.spec.has(PERCEPTION_DOCUMENT):
            doc = self._perceive_document(payload, file_path, task_hint)
            if doc:
                artifacts["document"] = doc
        if self.spec.has(PERCEPTION_IMAGE):
            vis = self._perceive_vision(file_path)
            if vis:
                artifacts["vision"] = vis
        if self.spec.has(PERCEPTION_AUDIO):
            aud = self._perceive_audio(payload, file_path)
            if aud:
                artifacts["audio"] = aud

        normalized = dict(payload)
        if artifacts:
            normalized["_perception"] = artifacts
        return {
            "normalized_input": normalized,
            "type": self.spec.type,
            "modalities": list(self.spec.modalities),
            "artifacts": artifacts,
        }

    # ---- document ----
    def _resolve_text(self, payload: dict[str, Any], file_path: str) -> tuple[str, str]:
        for key in ("text", "content", "document_text", "document"):
            v = payload.get(key)
            if isinstance(v, str) and v.strip():
                return v[:_MAX_DOC_CHARS], f"payload.{key}"
        if file_path:
            p = Path(file_path)
            if p.suffix.lower() in _TEXT_EXT and p.is_file():
                try:
                    return p.read_text(encoding="utf-8", errors="ignore")[:_MAX_DOC_CHARS], "file"
                except OSError:
                    logger.debug("perception read text failed: %s", file_path, exc_info=True)
        return "", ""

    def _perceive_document(
        self, payload: dict[str, Any], file_path: str, task_hint: str
    ) -> dict[str, Any] | None:
        text, source = self._resolve_text(payload, file_path)
        if not text.strip():
            if file_path and Path(file_path).suffix.lower() not in _TEXT_EXT:
                return {
                    "status": "skipped",
                    "reason": "二进制文档抽取未在感知层接入（请走 direct_python 文档包或传 text/content）",
                    "file": file_path,
                }
            return None
        try:
            from app.infrastructure.rag.hybrid_retriever import HybridRetriever, RetrievedChunk
            from app.infrastructure.rag.semantic_chunker import SemanticChunker

            chunks = SemanticChunker().split_by_semantic(text)
            if not chunks:
                return {"status": "empty", "source": source}
            retr_chunks = [
                RetrievedChunk(
                    text=c.text,
                    score=0.0,
                    chunk_index=c.chunk_index,
                    char_start=c.char_start,
                    char_end=c.char_end,
                )
                for c in chunks
            ]
            retriever = HybridRetriever(embedder=None, top_k=_KEYPOINT_TOPK)
            retriever.index(retr_chunks)
            query = task_hint or text[:300]
            hits = retriever.retrieve(query)
            keypoints = [h.text.strip()[:600] for h in hits if h.text.strip()]
            return {
                "status": "ok",
                "source": source,
                "chunk_count": len(chunks),
                "keypoints": keypoints,
                "query": query[:120],
            }
        except RECOVERABLE_ERRORS:
            logger.debug("perceive_document failed", exc_info=True)
            return {"status": "error", "source": source}

    # ---- vision ----
    def _perceive_vision(self, file_path: str) -> dict[str, Any] | None:
        if not file_path or Path(file_path).suffix.lower() not in _IMAGE_EXT:
            return None
        if not Path(file_path).is_file():
            return {"status": "skipped", "reason": "图像文件不存在", "file": file_path}
        try:
            from PIL import Image

            from app.services.ocr_service import get_ocr_service

            with Image.open(file_path) as img:
                text = get_ocr_service().recognize(img) or ""
            text = text.strip()
            if not text:
                return {"status": "degraded", "reason": "OCR 未识别到文字或引擎未就绪", "file": file_path}
            return {"status": "ok", "ocr_text": text[:4000], "file": file_path}
        except ImportError:
            return {"status": "unavailable", "reason": "OCR/PIL 依赖未安装", "file": file_path}
        except RECOVERABLE_ERRORS:
            logger.debug("perceive_vision failed: %s", file_path, exc_info=True)
            return {"status": "error", "file": file_path}

    # ---- audio ----
    def _perceive_audio(self, payload: dict[str, Any], file_path: str) -> dict[str, Any] | None:
        transcript = payload.get("transcript") or payload.get("asr_text")
        if isinstance(transcript, str) and transcript.strip():
            return {"status": "ok", "transcript": transcript.strip()[:4000], "source": "payload"}
        if file_path and Path(file_path).suffix.lower() in _AUDIO_EXT:
            return {
                "status": "unavailable",
                "reason": "ASR 未接入；请在输入提供 transcript 字段",
                "file": file_path,
            }
        return None


__all__ = ["PerceptionPipeline"]
