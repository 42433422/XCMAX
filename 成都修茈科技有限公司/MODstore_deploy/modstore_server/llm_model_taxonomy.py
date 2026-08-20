"""模型分类与标准化能力发现。

供应商目录声明的模态和操作优先；当 ``/models`` 只返回模型 ID 时，
再使用可版本化的命名规则补齐。返回结构会明确标注能力来源，避免把推断当成
供应商承诺。
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Mapping, Optional, Set, Tuple

from modstore_server.llm_model_classification import classify_model as classify_model

Category = Literal["llm", "vlm", "image", "video", "audio", "embedding", "rerank", "other"]

CATEGORY_ORDER: Tuple[Category, ...] = (
    "llm",
    "vlm",
    "image",
    "video",
    "audio",
    "embedding",
    "rerank",
    "other",
)


def category_labels_zh() -> Dict[str, str]:
    return {
        "llm": "语言大模型 (LLM)",
        "vlm": "视觉 / 多模态 (VLM)",
        "image": "图像生成",
        "video": "视频生成",
        "audio": "语音 / 音频",
        "embedding": "向量嵌入",
        "rerank": "重排 / 相关性",
        "other": "其他",
    }


def supports_trial_chat(category: str) -> bool:
    return category in ("llm", "vlm")


def _string_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if str(item or "").strip()]
    return []


def _normalise_modality(value: Any) -> str:
    text = str(value or "").strip().lower().replace("_", "-")
    aliases = {
        "images": "image",
        "vision": "image",
        "voices": "audio",
        "voice": "audio",
        "speech": "audio",
        "embeddings": "embedding",
        "vectors": "embedding",
        "files": "file",
    }
    return aliases.get(text, text)


def _add_modalities(target: Set[str], values: Any) -> None:
    for value in _string_list(values):
        modality = _normalise_modality(value)
        if modality in {
            "text",
            "image",
            "audio",
            "video",
            "file",
            "embedding",
            "score",
        }:
            target.add(modality)


def _operation_from_name(value: Any) -> Optional[str]:
    text = str(value or "").strip().lower().replace("_", "-")
    compact = text.replace("-", "")
    if not text:
        return None
    if text in {"chat", "language", "code", "completions", "completion"}:
        return "chat"
    if compact in {"generatecontent", "generatemessage"}:
        return "chat"
    if "text-to-speech" in text or text == "tts" or compact == "speechsynthesis":
        return "text_to_speech"
    if (
        "speech-to-text" in text
        or text in {"stt", "transcription", "transcribe"}
        or compact == "recognizespeech"
    ):
        return "speech_to_text"
    if text in {"image", "text-to-image", "image-generation", "image-to-image"}:
        return "image_generation"
    if text in {"video", "text-to-video", "video-generation", "image-to-video"}:
        return "video_generation"
    if text in {"audio", "music", "audio-generation"}:
        return "audio_generation"
    if text in {"embedding", "embeddings"} or compact in {
        "embedcontent",
        "batchembedcontents",
    }:
        return "embeddings"
    if text in {"rerank", "reranker", "ranking"}:
        return "rerank"
    if text in {"moderation", "moderate"}:
        return "moderation"
    return None


def _infer_profile(provider: str, model_id: str) -> Tuple[Set[str], Set[str], Set[str]]:
    category = classify_model(provider, model_id)
    low = (model_id or "").lower()
    inputs: Set[str] = set()
    outputs: Set[str] = set()
    operations: Set[str] = set()

    if category == "llm":
        inputs.add("text")
        outputs.add("text")
        operations.add("chat")
    elif category == "vlm":
        inputs.update(("text", "image"))
        outputs.add("text")
        operations.update(("chat", "vision"))
        if "omni" in low:
            inputs.add("audio")
    elif category == "image":
        inputs.add("text")
        if any(x in low for x in ("image-to-image", "img2img", "i2i")):
            inputs.add("image")
        outputs.add("image")
        operations.add("image_generation")
    elif category == "video":
        inputs.add("text")
        if any(x in low for x in ("image-to-video", "i2v", "video-01")):
            inputs.add("image")
        outputs.add("video")
        operations.add("video_generation")
    elif category == "audio":
        if any(x in low for x in ("whisper", "speech-to-text", "transcri", "stt", "-asr", "asr-")):
            inputs.add("audio")
            outputs.add("text")
            operations.add("speech_to_text")
        elif any(x in low for x in ("tts", "text-to-speech", "speech-synth")):
            inputs.add("text")
            outputs.add("audio")
            operations.add("text_to_speech")
            if "voiceclone" in low or "voice-clone" in low:
                inputs.add("audio")
                operations.add("voice_cloning")
            if "voicedesign" in low or "voice-design" in low:
                operations.add("voice_design")
        else:
            inputs.add("text")
            outputs.add("audio")
            operations.add("audio_generation")
    elif category == "embedding":
        inputs.add("text")
        outputs.add("embedding")
        operations.add("embeddings")
    elif category == "rerank":
        inputs.add("text")
        outputs.add("score")
        operations.add("rerank")
    return inputs, outputs, operations


def _declared_profile(
    metadata: Mapping[str, Any],
) -> Tuple[Set[str], Set[str], Set[str], List[str]]:
    inputs: Set[str] = set()
    outputs: Set[str] = set()
    operations: Set[str] = set()
    evidence: List[str] = []
    architecture = metadata.get("architecture")
    if not isinstance(architecture, Mapping):
        architecture = {}

    for field, target in (
        ("input_modalities", inputs),
        ("inputModalities", inputs),
        ("output_modalities", outputs),
        ("outputModalities", outputs),
    ):
        value = metadata.get(field)
        if value is None:
            value = architecture.get(field)
        before = len(target)
        _add_modalities(target, value)
        if len(target) > before:
            evidence.append(field)

    modality = metadata.get("modality") or architecture.get("modality")
    if isinstance(modality, str) and "->" in modality:
        left, right = modality.split("->", 1)
        _add_modalities(inputs, [part.strip() for part in left.split("+")])
        _add_modalities(outputs, [part.strip() for part in right.split("+")])
        evidence.append("modality")

    declared_types: List[Any] = [
        metadata.get("type"),
        metadata.get("sub_type"),
        metadata.get("task"),
    ]
    declared_types.extend(_string_list(metadata.get("supportedGenerationMethods")))
    declared_types.extend(_string_list(metadata.get("supported_generation_methods")))
    for declared in declared_types:
        op = _operation_from_name(declared)
        if op:
            operations.add(op)
    if operations:
        evidence.append("provider_operations")

    caps = metadata.get("capabilities")
    if isinstance(caps, Mapping):
        cap_names = [key for key, enabled in caps.items() if bool(enabled)]
    else:
        cap_names = _string_list(caps)
    for cap in cap_names:
        op = _operation_from_name(cap)
        if op:
            operations.add(op)
        low = str(cap).strip().lower().replace("_", "-")
        if low in {"vision", "image-input"}:
            inputs.add("image")
            operations.add("vision")
        elif low in {"audio-input", "speech-input"}:
            inputs.add("audio")
        elif low in {"audio-output", "speech-output"}:
            outputs.add("audio")
    if cap_names:
        evidence.append("capabilities")

    supported_parameters = {
        str(item).strip().lower() for item in _string_list(metadata.get("supported_parameters"))
    }
    if supported_parameters & {"tools", "tool_choice", "function_call", "functions"}:
        operations.add("tool_calling")
    if supported_parameters & {"response_format", "structured_outputs", "json_schema"}:
        operations.add("structured_output")
    if supported_parameters & {"reasoning", "reasoning_effort", "include_reasoning"}:
        operations.add("reasoning")
    if supported_parameters:
        evidence.append("supported_parameters")
    if metadata.get("thinking") is True:
        operations.add("reasoning")
        evidence.append("thinking")
    if metadata.get("supported_voices"):
        inputs.add("text")
        outputs.add("audio")
        operations.add("text_to_speech")
        evidence.append("supported_voices")

    # 模态本身是供应商声明的能力，可直接映射为标准操作。
    if "video" in outputs:
        operations.add("video_generation")
    if "image" in outputs:
        operations.add("image_generation")
    if "embedding" in outputs:
        operations.add("embeddings")
    if "score" in outputs:
        operations.add("rerank")
    if "audio" in inputs and "text" in outputs:
        operations.add("speech_to_text")
    if "text" in inputs and "audio" in outputs:
        operations.add("text_to_speech")
    elif "audio" in outputs:
        operations.add("audio_generation")

    if "chat" in operations:
        inputs.add("text")
        outputs.add("text")
    if "image_generation" in operations:
        inputs.add("text")
        outputs.add("image")
    if "video_generation" in operations:
        inputs.add("text")
        outputs.add("video")
    if "text_to_speech" in operations:
        inputs.add("text")
        outputs.add("audio")
    if "speech_to_text" in operations:
        inputs.add("audio")
        outputs.add("text")
    if "audio_generation" in operations:
        outputs.add("audio")
    if "embeddings" in operations:
        inputs.add("text")
        outputs.add("embedding")
    if "rerank" in operations:
        inputs.add("text")
        outputs.add("score")
    if "image" in inputs and "text" in outputs:
        operations.add("vision")
    return inputs, outputs, operations, sorted(set(evidence))


def _category_from_profile(
    fallback: Category, inputs: Set[str], outputs: Set[str], operations: Set[str]
) -> Category:
    if "video_generation" in operations or "video" in outputs:
        return "video"
    if "image_generation" in operations or "image" in outputs:
        return "image"
    if operations & {"text_to_speech", "speech_to_text", "audio_generation"}:
        return "audio"
    if "audio" in outputs and "text" not in outputs:
        return "audio"
    if "embeddings" in operations or "embedding" in outputs:
        return "embedding"
    if "rerank" in operations or "score" in outputs:
        return "rerank"
    if "vision" in operations or "image" in inputs:
        return "vlm"
    if "chat" in operations:
        return "llm"
    return fallback


def discover_model_capabilities(
    provider: str,
    model_id: str,
    metadata: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """把各厂商不同的模型字段归一化，同时保留可审计的推断来源。"""

    raw: Mapping[str, Any] = metadata or {}
    declared_in, declared_out, declared_ops, evidence = _declared_profile(raw)
    inferred_in, inferred_out, inferred_ops = _infer_profile(provider, model_id)
    inputs = set(declared_in)
    outputs = set(declared_out)
    operations = set(declared_ops)

    used_inference = False
    if not inputs:
        inputs.update(inferred_in)
        used_inference = bool(inferred_in)
    if not outputs:
        outputs.update(inferred_out)
        used_inference = used_inference or bool(inferred_out)
    if not operations:
        operations.update(inferred_ops)
        used_inference = used_inference or bool(inferred_ops)
    else:
        # 原生目录常只声明大类，模型 ID 仍可补齐 TTS/STT 等精确操作。
        for operation in inferred_ops:
            if operation not in operations and operation not in {"chat"}:
                operations.add(operation)
                used_inference = True

    if "image" in inputs and "text" in outputs:
        operations.add("vision")
    fallback_category = classify_model(provider, model_id)
    category = _category_from_profile(fallback_category, inputs, outputs, operations)
    origin = str(raw.get("_catalog_origin") or "").strip()
    if evidence and used_inference:
        source = "hybrid"
        confidence = "mixed"
    elif evidence:
        source = "provider_metadata"
        confidence = "declared"
    elif origin == "fallback":
        source = "fallback_inference"
        confidence = "inferred"
    else:
        source = "model_id_inference"
        confidence = "inferred"

    return {
        "category": category,
        "input_modalities": sorted(inputs),
        "output_modalities": sorted(outputs),
        "operations": sorted(operations),
        "runtime_selectable": "chat" in operations and "text" in outputs,
        "source": source,
        "confidence": confidence,
        "evidence": evidence or ["model_id"],
    }


def _positive_int(value: Any) -> Optional[int]:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _public_provider_metadata(metadata: Mapping[str, Any]) -> Dict[str, Any]:
    architecture = metadata.get("architecture")
    if not isinstance(architecture, Mapping):
        architecture = {}
    context_window = _positive_int(
        metadata.get("context_length")
        or metadata.get("inputTokenLimit")
        or metadata.get("input_token_limit")
        or architecture.get("context_length")
    )
    max_output_tokens = _positive_int(
        metadata.get("outputTokenLimit")
        or metadata.get("output_token_limit")
        or metadata.get("max_completion_tokens")
    )
    out: Dict[str, Any] = {}
    if context_window:
        out["context_window"] = context_window
    if max_output_tokens:
        out["max_output_tokens"] = max_output_tokens
    provider_type = str(metadata.get("type") or metadata.get("sub_type") or "").strip()
    if provider_type:
        out["provider_type"] = provider_type
    display_name = str(metadata.get("display_name") or metadata.get("displayName") or "").strip()
    if display_name:
        out["display_name"] = display_name[:256]
    generation_methods = _string_list(
        metadata.get("supportedGenerationMethods") or metadata.get("supported_generation_methods")
    )
    if generation_methods:
        out["supported_generation_methods"] = sorted(set(generation_methods))
    parameters = _string_list(metadata.get("supported_parameters"))
    if parameters:
        out["supported_parameters"] = sorted(set(parameters))
    return out


def _category_sort_key(cat: str) -> int:
    try:
        return CATEGORY_ORDER.index(cat)  # type: ignore[arg-type]
    except ValueError:
        return len(CATEGORY_ORDER)


def build_models_detailed(
    provider: str,
    model_ids: List[str],
    metadata_by_id: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for mid in model_ids:
        mid = (mid or "").strip()
        if not mid:
            continue
        metadata = (metadata_by_id or {}).get(mid) or {}
        capabilities = discover_model_capabilities(provider, mid, metadata)
        public_metadata = _public_provider_metadata(metadata)
        display_name = str(public_metadata.get("display_name") or mid)
        rows.append(
            {
                "id": mid,
                "display_name": display_name,
                "category": capabilities["category"],
                "capabilities": {
                    "input_modalities": capabilities["input_modalities"],
                    "output_modalities": capabilities["output_modalities"],
                    "operations": capabilities["operations"],
                },
                "runtime_selectable": capabilities["runtime_selectable"],
                "capability_source": capabilities["source"],
                "capability_confidence": capabilities["confidence"],
                "capability_evidence": capabilities["evidence"],
                "provider_metadata": public_metadata,
            }
        )
    rows.sort(key=lambda r: (_category_sort_key(r["category"]), r["id"]))
    return rows


def media_counts_from_detailed(models_detailed: List[Dict[str, Any]]) -> Dict[str, int]:
    """按 taxonomy 分类统计，供钱包磁贴展示生图/生视频能力。"""
    counts: Dict[str, int] = dict.fromkeys(CATEGORY_ORDER, 0)
    for md in models_detailed or []:
        cat = str(md.get("category") or "other")
        if cat not in counts:
            cat = "other"
        counts[cat] += 1
    return counts
