from __future__ import annotations

import asyncio
import base64
import logging
import os
import re
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass

from app.utils.operational_errors import BOUNDARY_ERRORS, RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

DEFAULT_EDGE_VOICE = "zh-CN-XiaoxiaoNeural"
DEFAULT_MIMO_VOICE = "冰糖"
_CACHE_MAX_SIZE = 50
_EDGE_TIMEOUT_S = 15.0
_EDGE_COOLDOWN_S = 300.0


class TtsUpstreamBlockedError(RuntimeError):
    """语音上游拒绝握手（例如 edge-tts 403），需冷却后重试或改用离线朗读。"""


_EDGE_VOICE_RE = re.compile(r"^[a-z]{2,3}-[A-Z]{2,3}-[A-Za-z]+Neural$")
_TTS_CACHE: OrderedDict[tuple[str, str, str, str, str], dict[str, str]] = OrderedDict()
_CACHE_LOCK = threading.Lock()
_WARMUP_STARTED = False
_WARMUP_LOCK = threading.Lock()
_EDGE_BLOCKED_UNTIL = 0.0
_EDGE_BLOCK_LOCK = threading.Lock()

_HARDCODED_PRO_PHRASES = [
    "您好，我是修茈。我可以帮您控制整个系统：产品管理、原材料仓库、出货单、客户管理、标签打印等。请告诉我您需要做什么？",
    "您好，我是修茈，可以协助您处理产品、原材料、出货单、客户和标签打印。",
    "我可以帮您控制整个系统，请告诉我您现在要做什么。",
    "您好，我是您的 AI 助理，目前已经开始实时监控，很高兴为您处理发货单相关事宜",
    "已识别发货单，正在自动生成...",
    "已自动打印发货单。",
    "自动打印请求失败",
    "工具执行成功",
    "任务执行完成",
    "请补充必要信息后继续。",
    "已退出工作模式，球体已恢复为青色；监控列表与每 10 秒刷新已停止。",
    "您好！我是 XCAGI 智能助手，很高兴为您服务！",
    "您好！欢迎使用 XCAGI 系统！",
    "今天需要我帮您做什么？",
]

_COMMON_PHRASES = [
    "好的",
    "收到您的需求",
    "正在处理",
    "请稍等",
    "我已记录",
    "马上为您执行",
    "已开始执行",
    "执行完成",
    "任务已完成",
    "结果已更新",
    "已为您生成",
    "正在为您查询",
    "查询完成",
    "正在为您整理",
    "整理完成",
    "正在加载数据",
    "加载完成",
    "已成功保存",
    "保存完成",
    "修改已生效",
    "设置已更新",
    "已为您提交",
    "提交成功",
    "请确认以下信息",
    "请补充必要信息",
    "参数不完整",
    "输入格式有误",
    "暂未找到匹配结果",
    "已找到相关结果",
    "正在优化答案",
    "已为您切换到专业模式",
    "专业模式已开启",
    "正在调用工具",
    "工具调用成功",
    "正在重试",
    "重试成功",
    "网络稍慢，请稍后",
    "系统繁忙，请稍后再试",
    "已为您创建任务",
    "任务正在后台运行",
    "后台任务已结束",
    "正在为您生成发货单",
    "发货单生成完成",
    "正在准备打印内容",
    "打印内容已准备好",
    "已为您解析产品信息",
    "产品信息解析完成",
    "正在同步数据",
    "数据同步完成",
    "感谢您的等待",
    "请告诉我您需要做什么",
]


def _build_warmup_phrases(limit: int) -> list[str]:
    if limit <= 0:
        return []
    merged = [*_HARDCODED_PRO_PHRASES, *_COMMON_PHRASES]
    ordered_unique: list[str] = []
    seen: set[str] = set()
    for phrase in merged:
        text = (phrase or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        ordered_unique.append(text)
        if len(ordered_unique) >= limit:
            break
    return ordered_unique


@dataclass(frozen=True)
class TtsRequest:
    text: str
    voice: str = DEFAULT_EDGE_VOICE
    lang: str = "zh"
    rate: str | None = None
    pitch: str | None = None


def _coalesce_voice(voice: str | None, speaker_id: str | None, lang: str) -> str:
    for candidate in (voice, speaker_id):
        v = (candidate or "").strip()
        if v and _EDGE_VOICE_RE.match(v):
            return v
    # 目前只实现中文默认；未来可扩展基于 lang 选默认 voice
    _ = (lang or "").strip().lower()
    return DEFAULT_EDGE_VOICE


def _coalesce_mimo_voice(voice: str | None, speaker_id: str | None) -> str:
    """Edge Neural id 不能直接给 MiMo；未显式指定 MiMo 音色时用默认冰糖。"""
    for candidate in (voice, speaker_id):
        v = (candidate or "").strip()
        if not v or _EDGE_VOICE_RE.match(v):
            continue
        return v
    return DEFAULT_MIMO_VOICE


def _normalize_cache_key(
    *, text: str, voice: str, lang: str, rate: str | None, pitch: str | None
) -> tuple[str, str, str, str, str]:
    return (
        text.strip(),
        voice.strip(),
        (lang or "zh").strip().lower(),
        (rate or "").strip(),
        (pitch or "").strip(),
    )


def _get_cache(key: tuple[str, str, str, str, str]) -> dict[str, str] | None:
    with _CACHE_LOCK:
        payload = _TTS_CACHE.get(key)
        if payload is None:
            return None
        _TTS_CACHE.move_to_end(key)
        return dict(payload)


def _set_cache(key: tuple[str, str, str, str, str], payload: dict[str, str]) -> None:
    with _CACHE_LOCK:
        _TTS_CACHE[key] = dict(payload)
        _TTS_CACHE.move_to_end(key)
        while len(_TTS_CACHE) > _CACHE_MAX_SIZE:
            _TTS_CACHE.popitem(last=False)


def _edge_cooldown_seconds() -> float:
    try:
        return max(0.0, float(os.environ.get("XCAGI_TTS_EDGE_COOLDOWN_S", _EDGE_COOLDOWN_S)))
    except (TypeError, ValueError):
        return _EDGE_COOLDOWN_S


def _is_edge_forbidden(exc: BaseException) -> bool:
    """识别 edge-tts / aiohttp 的 403 握手拒绝，而不是把它当成普通 500。"""
    status = getattr(exc, "status", None)
    if status is None:
        response = getattr(exc, "response", None)
        status = getattr(response, "status", None)
    if status == 403:
        return True
    text = str(exc or "")
    return "Invalid response status" in text and "403" in text


def _raise_if_edge_blocked() -> None:
    with _EDGE_BLOCK_LOCK:
        remaining = _EDGE_BLOCKED_UNTIL - time.monotonic()
    if remaining > 0:
        raise TtsUpstreamBlockedError(
            "Edge 语音上游此前拒绝了握手（HTTP 403），已暂停重试约 "
            f"{int(remaining)} 秒；请检查系统时间/网络，或改用离线语音包。"
        )


def _trip_edge_block(exc: BaseException) -> None:
    global _EDGE_BLOCKED_UNTIL
    cooldown = _edge_cooldown_seconds()
    with _EDGE_BLOCK_LOCK:
        _EDGE_BLOCKED_UNTIL = max(_EDGE_BLOCKED_UNTIL, time.monotonic() + cooldown)
    logger.warning(
        "Edge TTS 上游握手被拒绝（403），暂停调用 %.0f 秒：%s",
        cooldown,
        type(exc).__name__,
    )


def trigger_common_tts_warmup() -> None:
    """
    后台预热 50 条高频短语，减少专业模式首轮播报时延。
    只会启动一次，不阻塞请求线程。
    """

    def _warmup_worker() -> None:
        for phrase in _build_warmup_phrases(_CACHE_MAX_SIZE):
            try:
                synthesize_to_data_uri(text=phrase, lang="zh", voice=DEFAULT_EDGE_VOICE)
            except TtsUpstreamBlockedError:
                # 上游 403 已触发熔断，继续重试只会加重拒绝，直接结束预热。
                logger.info("TTS 预热因上游 403 停止，后续请求将快速失败并提示离线方案")
                break
            except RECOVERABLE_ERRORS:
                # 预热失败不影响主流程；首次真实请求仍可按需合成。
                continue

    global _WARMUP_STARTED
    with _WARMUP_LOCK:
        if _WARMUP_STARTED:
            return
        _WARMUP_STARTED = True

    worker = threading.Thread(target=_warmup_worker, name="tts-common-warmup", daemon=True)
    worker.start()


async def _synthesize_mp3_bytes(req: TtsRequest) -> bytes:
    import edge_tts

    kwargs: dict = {"text": req.text, "voice": req.voice}
    if req.rate:
        kwargs["rate"] = req.rate
    if req.pitch:
        kwargs["pitch"] = req.pitch
    chunks: list[bytes] = []
    async with asyncio.timeout(_EDGE_TIMEOUT_S):
        communicate = edge_tts.Communicate(**kwargs)
        async for item in communicate.stream():
            if item.get("type") == "audio":
                data = item.get("data")
                if isinstance(data, (bytes, bytearray)) and data:
                    chunks.append(bytes(data))
    return b"".join(chunks)


def _run_edge_sync(req: TtsRequest) -> bytes:
    try:
        return asyncio.run(_synthesize_mp3_bytes(req))
    except RuntimeError as e:
        # 兼容未来环境：如果已存在事件循环（如改成 async server），用新 loop 执行
        if "asyncio.run()" not in str(e):
            raise
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            return loop.run_until_complete(_synthesize_mp3_bytes(req))
        finally:
            try:
                loop.close()
            finally:
                asyncio.set_event_loop(None)


def _synthesize_edge_mp3(req: TtsRequest) -> bytes:
    _raise_if_edge_blocked()
    try:
        return _run_edge_sync(req)
    except TtsUpstreamBlockedError:
        raise
    except BOUNDARY_ERRORS as e:
        # 语音 SDK 抛出的自定义异常可能不属于 RECOVERABLE_ERRORS；
        # 这里是集成边界，必须转换为可诊断错误，不能让 /api/tts 变成 500。
        if _is_edge_forbidden(e):
            _trip_edge_block(e)
            raise TtsUpstreamBlockedError(
                "Edge 语音上游拒绝了握手（HTTP 403）；已暂停重试，请检查系统时间/网络，"
                "或改用离线语音包。"
            ) from e
        if isinstance(e, RECOVERABLE_ERRORS):
            raise
        raise RuntimeError(f"Edge TTS 调用失败：{type(e).__name__}") from e


def synthesize_to_data_uri(
    *,
    text: str,
    voice: str | None = None,
    speaker_id: str | None = None,
    lang: str = "zh",
    rate: str | None = None,
    pitch: str | None = None,
) -> dict:
    """
    统一 TTS：优先 MiMo-V2.5，失败回退 Edge 神经音。

    返回:
    {
      "audioBase64": "data:audio/...;base64,...",
      "voice": "...",
      "lang": "...",
      "provider": "mimo" | "edge"
    }
    """
    text_norm = (text or "").strip()
    if not text_norm:
        raise ValueError("text is empty")

    edge_voice = _coalesce_voice(voice, speaker_id, lang)
    mimo_voice = _coalesce_mimo_voice(voice, speaker_id)
    normalized_lang = (lang or "zh").strip().lower()
    # 缓存键含引擎链标记，避免旧 edge-only 缓存挡住 mimo
    cache_voice = f"mimo:{mimo_voice}|edge:{edge_voice}"
    key = _normalize_cache_key(
        text=text_norm, voice=cache_voice, lang=normalized_lang, rate=rate, pitch=pitch
    )
    cache_hit = _get_cache(key)
    if cache_hit:
        return cache_hit

    # 1) MiMo
    try:
        from app.domain.shared_services.mimo_tts_service import is_configured, synthesize_mimo_bytes

        if is_configured():
            audio_bytes, meta = synthesize_mimo_bytes(text_norm, voice=mimo_voice)
            mime = str(meta.get("mime") or "audio/wav")
            b64 = base64.b64encode(audio_bytes).decode("ascii")
            payload = {
                "audioBase64": f"data:{mime};base64,{b64}",
                "voice": str(meta.get("voice") or mimo_voice),
                "lang": normalized_lang,
                "provider": "mimo",
            }
            _set_cache(key, payload)
            return payload
    except RECOVERABLE_ERRORS as exc:
        logger.info("MiMo TTS unavailable, falling back to Edge: %s", exc)

    # 2) Edge neural
    req = TtsRequest(text=text_norm, voice=edge_voice, lang=normalized_lang, rate=rate, pitch=pitch)
    mp3_bytes = _synthesize_edge_mp3(req)
    if not mp3_bytes:
        raise RuntimeError("edge-tts returned empty audio")

    b64 = base64.b64encode(mp3_bytes).decode("ascii")
    payload = {
        "audioBase64": f"data:audio/mpeg;base64,{b64}",
        "voice": edge_voice,
        "lang": req.lang,
        "provider": "edge",
    }
    _set_cache(key, payload)
    return payload
