"""Versioned provider/model-name classification rules."""

from __future__ import annotations

from typing import Literal

Category = Literal["llm", "vlm", "image", "video", "audio", "embedding", "rerank", "other"]


def classify_model(provider: str, model_id: str) -> Category:
    s = (model_id or "").strip()
    if not s:
        return "other"
    low = s.lower()
    prov = (provider or "").strip().lower()

    if any(x in low for x in ("embedding", "text-embedding", "embed-", "embed/")):
        return "embedding"
    if any(x in low for x in ("rerank", "reranker", "rank_", "/rank")):
        return "rerank"
    if any(
        x in low
        for x in (
            "whisper",
            "tts",
            "text-to-speech",
            "speech-to-text",
            "transcribe",
            "transcription",
            "speech-",
            "-asr",
            "asr-",
            "audio-",
            "audio/",
            "voice-",
            "music-",
        )
    ):
        return "audio"

    # 明确非对话主场景：审核、老补全、检索等
    if any(
        x in low
        for x in (
            "moderation",
            "davinci",
            "babbage",
            "text-search",
            "ada-002",
            "ada-001",
        )
    ):
        return "other"
    if low.startswith("ada") and prov == "openai":
        return "other"

    # 视频（全局命名，优先于生图：避免 wan2.*-i2v 被 wan2 误判为生图）
    if any(
        x in low
        for x in (
            "sora",
            "veo-",
            "veo_",
            "veo2",
            "veo3",
            "video-generation",
            "videogen",
            "text-to-video",
            "text2video",
            "image-to-video",
            "cogvideo",
            "cogvideox",
            "kling",
            "seedance",
            "hailuo",
            "runway",
            "luma",
            "minimax-video",
            "video-01",
            "-i2v",
            "-t2v",
            "i2v-",
            "t2v-",
            "wan-i2v",
            "hunyuan-video",
        )
    ):
        return "video"

    # 图像（全局命名）
    if any(
        x in low
        for x in (
            "dall-e",
            "dall_e",
            "dalle",
            "gpt-image",
            "gpt_image",
            "imagen",
            "image-generation",
            "text-to-image",
            "text2image",
            "image-to-image",
            "image-preview",
            "stable-diffusion",
            "sdxl",
            "sd3",
            "flux.",
            "flux-",
            "flux/",
            "flux.1",
            "seedream",
            "jimeng",
            "cogview",
            "kolors",
            "wanx",
            "wan2",
            "playground-v2",
            "recraft",
            "ideogram",
            "midjourney",
        )
    ):
        return "image"

    # 多模态 / 视觉
    if "vision" in low or "vl-" in low or "vlm" in low:
        return "vlm"
    if "deepseek-vl" in low or "qwen-vl" in low or "llava" in low:
        return "vlm"
    if "omni" in low:
        return "vlm"
    if "gpt-4o" in low or "gpt-4.1" in low:
        return "vlm"
    if "gpt-4-turbo" in low:
        return "vlm"
    if prov == "google":
        if "imagen" in low:
            return "image"
        if "veo" in low:
            return "video"
        if low.startswith("gemini") and "embed" not in low:
            # Gemini 1.5+ 默认按多模态入口归类
            if low.startswith("gemini-1.5") or low.startswith("gemini-2"):
                return "vlm"
    if prov == "anthropic" and (
        "claude-3" in low or "claude-sonnet" in low or "claude-opus" in low
    ):
        return "vlm"

    # 聚合网关 / OpenAI 兼容：SiliconFlow、百炼、Kimi、MiniMax、Groq、Together、OpenRouter 等
    if prov in (
        "siliconflow",
        "together",
        "groq",
        "openrouter",
        "dashscope",
        "moonshot",
        "xiaomi",
        "minimax",
        "doubao",
        "wenxin",
        "hunyuan",
        "zhipu",
        "xunfei",
        "yi",
        "stepfun",
        "baichuan",
        "sensetime",
    ):
        if any(
            x in low
            for x in (
                "stable-diffusion",
                "sdxl",
                "flux.",
                "flux/",
                "flux-1",
                "flux.1",
                "text-to-image",
                "image-to-image",
                "kolors",
                "playground-v2",
                "dall-e",
                "wanx",
                "text2image",
                "wan2",
                "seedream",
            )
        ):
            return "image"
        if any(
            x in low
            for x in (
                "text-to-video",
                "image-to-video",
                "video-generation",
                "cogvideox",
                "wan-i2v",
                "kling",
                "i2v",
                "t2v",
                "video-01",
                "hailuo",
                "seedance",
            )
        ):
            return "video"
        if "embed" in low or "bge-" in low or "/rerank" in low or "reranker" in low:
            return "other"
        if (
            "vl" in low
            or "vision" in low
            or "qwen-vl" in low
            or "llava" in low
            or "glm-4.5v" in low
            or "glm-4.6" in low
        ):
            return "vlm"
        if "omni" in low:
            return "vlm"
        if prov == "minimax" and ("speech" in low or "voice" in low or "music" in low):
            return "other"

    return "llm"
