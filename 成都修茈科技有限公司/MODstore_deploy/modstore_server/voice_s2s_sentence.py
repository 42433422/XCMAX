"""流式 LLM 输出 → 可分句 TTS 的句子切分（语音 S2S 管线）。"""

from __future__ import annotations

import re

_SENTENCE_END = re.compile(r"(?<=[。！？!?；;\n])")
_SENTENCE_END_AT_TAIL = re.compile(r"[。！？!?；;\n]\s*$")
_CLAUSE_END = re.compile(r"(?<=[，、,：:])")
_CLAUSE_END_AT_TAIL = re.compile(r"[，、,：:]\s*$")


def _clean_tts_text(text: str) -> str:
    t = (text or "").strip()
    if not t:
        return ""
    t = re.sub(r"\s+", " ", t)
    return t


def _completed_parts(text: str, splitter: re.Pattern[str], tail_re: re.Pattern[str]) -> list[str]:
    parts = [p for p in splitter.split(text) if p.strip()]
    if not parts:
        return []
    return parts if tail_re.search(text) else parts[:-1]


def _natural_prefix_len(text: str, min_len: int) -> int:
    if min_len <= 0 or len(text) < min_len:
        return 0
    window = text[: min(len(text), max(min_len + 12, int(min_len * 1.8)))]
    matches = list(re.finditer(r"[，、,：:]\s*|\s+", window))
    for match in reversed(matches):
        if match.end() >= min_len:
            return match.end()
    return 0


class VoiceStreamSentenceSplitter:
    """增量切句：已 emit 的句子不会重复返回。"""

    def __init__(
        self,
        *,
        early_clause: bool = False,
        first_chunk_len: int = 0,
        early_clause_min_len: int = 16,
    ) -> None:
        self._buffer = ""
        self._emitted = ""
        self._early_clause = early_clause
        self._first_chunk_len = max(0, first_chunk_len)
        self._early_clause_min_len = max(6, early_clause_min_len)
        self._first_emitted = False

    def reset(self) -> None:
        self._buffer = ""
        self._emitted = ""
        self._first_emitted = False

    def feed(self, so_far: str) -> list[str]:
        self._buffer = _clean_tts_text(so_far)
        if not self._buffer or len(self._buffer) <= len(self._emitted):
            return []

        pending = self._buffer[len(self._emitted) :]
        if not pending.strip():
            return []

        out: list[str] = []

        complete = _completed_parts(self._buffer, _SENTENCE_END, _SENTENCE_END_AT_TAIL)
        if self._early_clause:
            tail_start = sum(len(p) for p in complete)
            tail = self._buffer[tail_start:]
            clauses = _completed_parts(tail, _CLAUSE_END, _CLAUSE_END_AT_TAIL)
            complete = complete + [
                c for c in clauses if len(c.strip()) >= self._early_clause_min_len
            ]

        if not complete and not self._first_emitted and self._first_chunk_len:
            prefix_len = _natural_prefix_len(pending, self._first_chunk_len)
            if prefix_len:
                chunk = pending[:prefix_len].strip()
                if chunk:
                    out.append(chunk)
                    self._emitted = self._buffer[: len(self._emitted) + prefix_len]
                    self._first_emitted = True
                    return out

        if not complete:
            return out

        rebuilt = ""
        fresh: list[str] = []
        for seg in complete:
            rebuilt += seg
            if len(rebuilt) > len(self._emitted):
                piece = self._buffer[len(self._emitted) : len(rebuilt)].strip()
                if piece:
                    fresh.append(piece)
                self._emitted = rebuilt[: len(rebuilt)]

        out.extend(fresh)
        if fresh:
            self._first_emitted = True
        return out

    def finish(self, so_far: str) -> list[str]:
        self._buffer = _clean_tts_text(so_far)
        if not self._buffer:
            return []
        rest = self._buffer[len(self._emitted) :].strip()
        if not rest:
            return []
        self._emitted = self._buffer
        return [rest]
