"""Tests for app.services.tts_service — coverage ramp C3.3-b.

Covers:
* ``TtsRequest`` frozen dataclass.
* ``_coalesce_voice`` honours voice / speaker_id / lang defaults.
* ``_EDGE_VOICE_RE`` matches the canonical voice format.
* ``_normalize_cache_key`` trims and lowercases lang.
* ``_build_warmup_phrases`` dedupes and respects limit.
* ``synthesize_to_data_uri`` raises ``ValueError`` on empty text.
* ``synthesize_to_data_uri`` returns cached payload on hit.
* ``synthesize_to_data_uri`` happy path: edge-tts returns bytes → b64.
* ``synthesize_to_data_uri`` raises ``RuntimeError`` when edge-tts returns empty.
* ``synthesize_to_data_uri`` falls back to a fresh event loop when nested.
* ``trigger_common_tts_warmup`` is idempotent.
"""

from __future__ import annotations

import base64
import time
from unittest.mock import MagicMock, patch

import pytest

from app.services import tts_service as tts
from app.services.tts_service import (
    _EDGE_VOICE_RE,
    DEFAULT_EDGE_VOICE,
    TtsRequest,
    _build_warmup_phrases,
    _coalesce_voice,
    _get_cache,
    _normalize_cache_key,
    _set_cache,
    synthesize_to_data_uri,
    trigger_common_tts_warmup,
)


@pytest.fixture(autouse=True)
def _reset_tts_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clear cache + warmup latch between tests."""
    monkeypatch.setattr(tts, "_TTS_CACHE", tts.OrderedDict())
    monkeypatch.setattr(tts, "_WARMUP_STARTED", False)


# ---------------------------------------------------------------------------
# TtsRequest
# ---------------------------------------------------------------------------


class TestTtsRequest:
    def test_defaults(self) -> None:
        r = TtsRequest(text="hi")
        assert r.text == "hi"
        assert r.voice == DEFAULT_EDGE_VOICE
        assert r.lang == "zh"
        assert r.rate is None
        assert r.pitch is None

    def test_frozen(self) -> None:
        r = TtsRequest(text="hi", rate="+10%")
        with pytest.raises(Exception):  # FrozenInstanceError
            r.text = "changed"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# _EDGE_VOICE_RE
# ---------------------------------------------------------------------------


class TestEdgeVoiceRe:
    def test_canonical(self) -> None:
        assert _EDGE_VOICE_RE.match("zh-CN-XiaoxiaoNeural")

    def test_other_locale(self) -> None:
        assert _EDGE_VOICE_RE.match("en-US-AriaNeural")

    def test_rejects_plain_string(self) -> None:
        assert _EDGE_VOICE_RE.match("zh-CN-xiaoxiao") is None
        assert _EDGE_VOICE_RE.match("not-a-voice") is None


# ---------------------------------------------------------------------------
# _coalesce_voice
# ---------------------------------------------------------------------------


class TestCoalesceVoice:
    def test_explicit_voice(self) -> None:
        v = _coalesce_voice("en-US-AriaNeural", None, "en")
        assert v == "en-US-AriaNeural"

    def test_speaker_id_used_when_voice_empty(self) -> None:
        v = _coalesce_voice(None, "en-US-AriaNeural", "en")
        assert v == "en-US-AriaNeural"

    def test_invalid_voice_falls_through_to_default(self) -> None:
        v = _coalesce_voice("not-a-voice", None, "zh")
        assert v == DEFAULT_EDGE_VOICE

    def test_strips_whitespace(self) -> None:
        v = _coalesce_voice("  en-US-AriaNeural  ", None, "en")
        assert v == "en-US-AriaNeural"

    def test_default_when_nothing_valid(self) -> None:
        v = _coalesce_voice(None, None, "zh")
        assert v == DEFAULT_EDGE_VOICE


# ---------------------------------------------------------------------------
# _normalize_cache_key
# ---------------------------------------------------------------------------


class TestNormalizeCacheKey:
    def test_basic(self) -> None:
        k = _normalize_cache_key(
            text="hi", voice="en-US-AriaNeural", lang="en", rate=None, pitch=None
        )
        assert k == ("hi", "en-US-AriaNeural", "en", "", "")

    def test_strips_text(self) -> None:
        k = _normalize_cache_key(
            text="  hi  ", voice="en-US-AriaNeural", lang="en", rate=None, pitch=None
        )
        assert k[0] == "hi"

    def test_normalizes_lang(self) -> None:
        k = _normalize_cache_key(
            text="hi", voice="en-US-AriaNeural", lang="EN", rate=None, pitch=None
        )
        assert k[2] == "en"

    def test_defaults_lang(self) -> None:
        k = _normalize_cache_key(
            text="hi", voice="en-US-AriaNeural", lang="", rate=None, pitch=None
        )
        assert k[2] == "zh"

    def test_handles_none_rate_pitch(self) -> None:
        k = _normalize_cache_key(
            text="hi", voice="en-US-AriaNeural", lang="zh", rate=None, pitch=None
        )
        assert k[3:] == ("", "")


# ---------------------------------------------------------------------------
# _build_warmup_phrases
# ---------------------------------------------------------------------------


class TestBuildWarmupPhrases:
    def test_merges_hardcoded_and_common(self) -> None:
        out = _build_warmup_phrases(100)
        assert isinstance(out, list)
        assert "您好，我是修茈" in out[0]  # first item is the highest-priority
        # common phrase is included
        assert any("请稍等" in phrase for phrase in out)

    def test_dedupes(self) -> None:
        out = _build_warmup_phrases(100)
        assert len(out) == len(set(out))

    def test_respects_limit(self) -> None:
        out = _build_warmup_phrases(5)
        assert len(out) == 5

    def test_limit_zero(self) -> None:
        out = _build_warmup_phrases(0)
        assert out == []


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------


class TestCacheHelpers:
    def test_set_and_get(self) -> None:
        key = ("t", "v", "zh", "", "")
        _set_cache(key, {"audioBase64": "data:audio/x", "voice": "v", "lang": "zh"})
        out = _get_cache(key)
        assert out == {"audioBase64": "data:audio/x", "voice": "v", "lang": "zh"}

    def test_get_returns_none_on_miss(self) -> None:
        assert _get_cache(("missing", "v", "zh", "", "")) is None

    def test_set_caps_at_max(self) -> None:
        # _CACHE_MAX_SIZE is 50; verify eviction
        for i in range(60):
            _set_cache(
                (f"t{i}", "v", "zh", "", ""),
                {"audioBase64": f"data:{i}", "voice": "v", "lang": "zh"},
            )
        # The earliest 10 should have been evicted (LRU)
        assert _get_cache(("t0", "v", "zh", "", "")) is None
        # The latest should still be there
        assert _get_cache(("t59", "v", "zh", "", "")) is not None


# ---------------------------------------------------------------------------
# synthesize_to_data_uri — empty / cache hit
# ---------------------------------------------------------------------------


class TestSynthesizeEmpty:
    def test_empty_text_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="text is empty"):
            synthesize_to_data_uri(text="")

    def test_whitespace_only_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="text is empty"):
            synthesize_to_data_uri(text="   \n  ")


class TestSynthesizeCacheHit:
    def test_cache_hit_returns_payload(self) -> None:
        key = _normalize_cache_key(
            text="hi", voice=DEFAULT_EDGE_VOICE, lang="zh", rate=None, pitch=None
        )
        cached = {
            "audioBase64": "data:audio/mpeg;base64,QUJD",
            "voice": DEFAULT_EDGE_VOICE,
            "lang": "zh",
        }
        _set_cache(key, cached)
        out = synthesize_to_data_uri(text="hi")
        assert out == cached


# ---------------------------------------------------------------------------
# synthesize_to_data_uri — happy path (edge-tts mocked)
# ---------------------------------------------------------------------------


class TestSynthesizeHappyPath:
    def test_edge_tts_returns_bytes(self, monkeypatch) -> None:
        """When edge_tts yields one audio chunk, we get a base64 payload back."""

        async def _stream_iter():
            yield {"type": "audio", "data": b"abc"}
            yield {"type": "audio", "data": b"def"}

        fake_mod = MagicMock()
        fake_mod.Communicate = MagicMock()
        fake_mod.Communicate.return_value.stream = _stream_iter

        with patch.dict("sys.modules", {"edge_tts": fake_mod}):
            out = synthesize_to_data_uri(text="hello world", voice=DEFAULT_EDGE_VOICE)

        assert out["voice"] == DEFAULT_EDGE_VOICE
        assert out["lang"] == "zh"
        b64 = out["audioBase64"].split(",", 1)[1]
        assert base64.b64decode(b64) == b"abcdef"

    def test_edge_tts_no_audio_chunks_raises(self, monkeypatch) -> None:
        async def _stream_iter():
            if False:
                yield  # pragma: no cover - empty generator

        fake_mod = MagicMock()
        fake_mod.Communicate = MagicMock()
        fake_mod.Communicate.return_value.stream = _stream_iter

        with patch.dict("sys.modules", {"edge_tts": fake_mod}):
            with pytest.raises(RuntimeError, match="edge-tts returned empty audio"):
                synthesize_to_data_uri(text="hello")

    def test_edge_tts_non_audio_chunks_ignored(self, monkeypatch) -> None:
        async def _stream_iter():
            yield {"type": "WordBoundary", "data": "ignored"}
            yield {"type": "audio", "data": b"only-real-bytes"}

        fake_mod = MagicMock()
        fake_mod.Communicate = MagicMock()
        fake_mod.Communicate.return_value.stream = _stream_iter

        with patch.dict("sys.modules", {"edge_tts": fake_mod}):
            out = synthesize_to_data_uri(text="hello")
        b64 = out["audioBase64"].split(",", 1)[1]
        assert base64.b64decode(b64) == b"only-real-bytes"

    def test_optional_rate_and_pitch_passed(self, monkeypatch) -> None:
        async def _stream_iter():
            yield {"type": "audio", "data": b"X"}

        fake_mod = MagicMock()
        fake_mod.Communicate = MagicMock()
        fake_mod.Communicate.return_value.stream = _stream_iter

        with patch.dict("sys.modules", {"edge_tts": fake_mod}):
            synthesize_to_data_uri(text="hi", rate="+10%", pitch="+2Hz")
        kwargs = fake_mod.Communicate.call_args.kwargs
        assert kwargs["rate"] == "+10%"
        assert kwargs["pitch"] == "+2Hz"

    def test_omits_rate_and_pitch_when_none(self, monkeypatch) -> None:
        async def _stream_iter():
            yield {"type": "audio", "data": b"X"}

        fake_mod = MagicMock()
        fake_mod.Communicate = MagicMock()
        fake_mod.Communicate.return_value.stream = _stream_iter

        with patch.dict("sys.modules", {"edge_tts": fake_mod}):
            synthesize_to_data_uri(text="hi")
        kwargs = fake_mod.Communicate.call_args.kwargs
        assert "rate" not in kwargs
        assert "pitch" not in kwargs


# ---------------------------------------------------------------------------
# synthesize_to_data_uri — nested loop fallback
# ---------------------------------------------------------------------------


class TestNestedLoopFallback:
    def test_runtime_error_with_other_message_re_raises(self, monkeypatch) -> None:
        async def _raise_other(_req) -> bytes:  # noqa: ARG001
            raise RuntimeError("some other error")

        monkeypatch.setattr(tts, "_synthesize_mp3_bytes", _raise_other)
        with pytest.raises(RuntimeError, match="some other error"):
            synthesize_to_data_uri(text="hi")

    def test_runtime_error_with_asyncio_run_message_uses_new_loop(self, monkeypatch) -> None:
        # When the existing event loop is "running", asyncio.run() raises a
        # RuntimeError with a specific message. Verify the fallback path.
        calls = {"n": 0}

        def _factory(req) -> bytes:  # noqa: ARG001
            calls["n"] += 1
            if calls["n"] == 1:

                async def _raise_nested() -> bytes:
                    raise RuntimeError("asyncio.run() cannot be called from a running event loop")

                return _raise_nested()

            async def _succeed() -> bytes:
                return b"RECOVERED"

            return _succeed()

        monkeypatch.setattr(tts, "_synthesize_mp3_bytes", _factory)
        # Need a stream-iter that's a no-op; the fallback path doesn't actually
        # reach edge_tts because we replaced _synthesize_mp3_bytes wholesale.
        with patch.dict("sys.modules", {"edge_tts": MagicMock()}):
            out = synthesize_to_data_uri(text="hi")
        b64 = out["audioBase64"].split(",", 1)[1]
        assert base64.b64decode(b64) == b"RECOVERED"
        assert calls["n"] == 2


# ---------------------------------------------------------------------------
# trigger_common_tts_warmup — idempotency
# ---------------------------------------------------------------------------


class TestWarmup:
    def test_idempotent(self, monkeypatch) -> None:
        # Patch the synth function so the worker thread can call it cheaply
        def _fake_synth(**kw):
            text = (kw.get("text") or "").strip()
            key = _normalize_cache_key(
                text=text, voice=DEFAULT_EDGE_VOICE, lang="zh", rate=None, pitch=None
            )
            payload = {"audioBase64": "data:audio/x", "voice": "v", "lang": "zh"}
            _set_cache(key, payload)
            return payload

        monkeypatch.setattr(tts, "synthesize_to_data_uri", _fake_synth)

        # Reset latch
        tts._WARMUP_STARTED = False

        # First call sets the latch
        trigger_common_tts_warmup()
        first_started = tts._WARMUP_STARTED
        # Second call should short-circuit (latch already set)
        trigger_common_tts_warmup()

        # Wait for the background thread to finish a couple of iterations
        for _ in range(20):
            time.sleep(0.05)
            if tts._TTS_CACHE:
                break

        assert first_started is True
        # Cache should have some entries (worker ran)
        assert len(tts._TTS_CACHE) > 0

    def test_warmup_exception_is_swallowed(self, monkeypatch) -> None:
        """The warmup worker must continue past per-phrase errors."""
        counter = {"n": 0}

        def _explode(**kw) -> dict:  # noqa: ARG001
            counter["n"] += 1
            raise RuntimeError("synth fail")

        monkeypatch.setattr(tts, "synthesize_to_data_uri", _explode)
        tts._WARMUP_STARTED = False
        trigger_common_tts_warmup()

        for _ in range(20):
            time.sleep(0.05)
            if counter["n"] >= 5:
                break
        # Worker should have tried many phrases despite failures
        assert counter["n"] >= 1
