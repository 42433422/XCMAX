# Copyright (c) 2024-2026, Daily
# SPDX-License-Identifier: BSD 2-Clause License
#
# Vendored from Pipecat (https://github.com/pipecat-ai/pipecat):
#   - pipecat/audio/turn/smart_turn/_whisper_features.py
#   - pipecat/audio/turn/smart_turn/local_smart_turn_v3.py
# Model weights: https://huggingface.co/pipecat-ai/smart-turn-v3 (BSD-2-Clause)
#
# 只做端点检测（end-of-turn）：判断用户这一段话是否说完，避免把语气词/半句话直接发出去。
"""Local smart-turn v3.2 end-of-turn detection (numpy + onnxruntime)."""

from __future__ import annotations

import io
import threading
import wave
from pathlib import Path
from typing import Any

import numpy as np

from app.utils.operational_errors import BOUNDARY_ERRORS

_MODEL_SAMPLE_RATE = 16000
_MODEL_PATH = Path(__file__).resolve().parent / "models" / "smart-turn-v3.2-cpu.onnx"

_session: Any = None
_session_lock = threading.Lock()

_N_FFT = 400
_HOP_LENGTH = 160
_N_MELS = 80
_MEL_FLOOR = 1e-10
_NORM_VARIANCE_EPS = 1e-7


def _hertz_to_mel_slaney(freq: np.ndarray) -> np.ndarray:
    min_log_hertz = 1000.0
    min_log_mel = 15.0
    logstep = 27.0 / np.log(6.4)
    freq = np.atleast_1d(np.asarray(freq, dtype=np.float64))
    mels = 3.0 * freq / 200.0
    log_region = freq >= min_log_hertz
    mels[log_region] = min_log_mel + np.log(freq[log_region] / min_log_hertz) * logstep
    return mels


def _mel_to_hertz_slaney(mels: np.ndarray) -> np.ndarray:
    min_log_hertz = 1000.0
    min_log_mel = 15.0
    logstep = np.log(6.4) / 27.0
    mels = np.atleast_1d(np.asarray(mels, dtype=np.float64))
    freq = 200.0 * mels / 3.0
    log_region = mels >= min_log_mel
    freq[log_region] = min_log_hertz * np.exp(logstep * (mels[log_region] - min_log_mel))
    return freq


def _build_mel_filterbank(
    num_frequency_bins: int,
    num_mel_filters: int,
    min_frequency: float,
    max_frequency: float,
    sampling_rate: int,
) -> np.ndarray:
    mel_min = float(_hertz_to_mel_slaney(np.array([min_frequency], dtype=np.float64))[0])
    mel_max = float(_hertz_to_mel_slaney(np.array([max_frequency], dtype=np.float64))[0])
    mel_freqs = np.linspace(mel_min, mel_max, num_mel_filters + 2)
    filter_freqs = _mel_to_hertz_slaney(mel_freqs)
    fft_freqs = np.linspace(0, sampling_rate // 2, num_frequency_bins)
    filter_diff = np.diff(filter_freqs)
    slopes = np.expand_dims(filter_freqs, 0) - np.expand_dims(fft_freqs, 1)
    down_slopes = -slopes[:, :-2] / filter_diff[:-1]
    up_slopes = slopes[:, 2:] / filter_diff[1:]
    mel_filters = np.maximum(np.zeros(1), np.minimum(down_slopes, up_slopes))
    enorm = 2.0 / (filter_freqs[2 : num_mel_filters + 2] - filter_freqs[:num_mel_filters])
    mel_filters *= np.expand_dims(enorm, 0)
    return mel_filters


def _periodic_hann_window(window_length: int) -> np.ndarray:
    return np.hanning(window_length + 1)[:-1]


_HANN_WINDOW = _periodic_hann_window(_N_FFT)
_MEL_FILTERS = _build_mel_filterbank(
    num_frequency_bins=_N_FFT // 2 + 1,
    num_mel_filters=_N_MELS,
    min_frequency=0.0,
    max_frequency=_MODEL_SAMPLE_RATE / 2.0,
    sampling_rate=_MODEL_SAMPLE_RATE,
)


def _power_spectrogram(waveform: np.ndarray, window: np.ndarray, frame_length: int, hop_length: int) -> np.ndarray:
    from numpy.lib.stride_tricks import sliding_window_view

    pad = frame_length // 2
    padded = np.pad(waveform.astype(np.float64), (pad, pad), mode="reflect")
    windows = sliding_window_view(padded, frame_length)[::hop_length]
    spec = np.fft.rfft(windows * window.astype(np.float64), axis=-1)
    return (np.abs(spec) ** 2).T


def compute_whisper_log_mel_features(audio: np.ndarray, *, do_normalize: bool = True) -> np.ndarray:
    """Whisper log-mel features, shape (80, 800); input must be 16 kHz mono."""
    if audio.ndim != 1:
        raise ValueError(f"Expected 1-D audio, got shape {audio.shape}")
    x = np.asarray(audio, dtype=np.float32)
    n_samples = _MODEL_SAMPLE_RATE * 8
    if x.size < n_samples:
        x = np.pad(x, (0, n_samples - x.size), mode="constant")
    elif x.size > n_samples:
        x = x[-n_samples:]
    if do_normalize:
        x = (x - x.mean()) / np.sqrt(x.var() + _NORM_VARIANCE_EPS)
    magnitudes = _power_spectrogram(x, _HANN_WINDOW, _N_FFT, _HOP_LENGTH)
    mel_spec = np.maximum(_MEL_FLOOR, _MEL_FILTERS.T @ magnitudes)
    log_spec = np.log10(mel_spec)[:, :-1]
    log_spec = np.maximum(log_spec, log_spec.max() - 8.0)
    return ((log_spec + 4.0) / 4.0).astype(np.float32)


def _load_session() -> Any:
    global _session
    if _session is not None:
        return _session
    with _session_lock:
        if _session is None:
            import onnxruntime as ort

            so = ort.SessionOptions()
            so.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
            so.inter_op_num_threads = 1
            so.intra_op_num_threads = 1
            so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            _session = ort.InferenceSession(str(_MODEL_PATH), sess_options=so)
    return _session


def _decode_wav_16k(wav_bytes: bytes) -> np.ndarray:
    with wave.open(io.BytesIO(wav_bytes), "rb") as handle:
        channels = handle.getnchannels()
        width = handle.getsampwidth()
        rate = handle.getframerate()
        frames = handle.readframes(handle.getnframes())
    if width != 2:
        raise ValueError("仅支持 16-bit PCM WAV")
    pcm = np.frombuffer(frames, dtype=np.int16)
    if channels > 1:
        pcm = pcm.reshape(-1, channels).mean(axis=1).astype(np.int16)
    audio = pcm.astype(np.float32) / 32768.0
    if rate != _MODEL_SAMPLE_RATE and audio.size:
        # 简单线性重采样，仅作为非 16k 输入的兜底；前端统一上传 16k WAV。
        target_size = max(1, int(audio.size * _MODEL_SAMPLE_RATE / rate))
        audio = np.interp(
            np.linspace(0, audio.size - 1, target_size), np.arange(audio.size), audio
        ).astype(np.float32)
    return audio


def predict_turn_complete(wav_bytes: bytes, threshold: float = 0.5) -> dict[str, Any]:
    """Return {"probability", "complete", "threshold"} for one utterance.

    threshold 由前端设置项传入（并按麦克风噪声自适应），默认 0.5。
    """
    audio = _decode_wav_16k(wav_bytes)
    if audio.size == 0:
        raise ValueError("录音内容为空")
    threshold = min(0.95, max(0.05, float(threshold)))
    features = np.expand_dims(compute_whisper_log_mel_features(audio), axis=0)
    outputs = _load_session().run(None, {"input_features": features})
    probability = float(np.asarray(outputs[0])[0].item())
    return {
        "probability": round(probability, 4),
        "complete": probability > threshold,
        "threshold": threshold,
    }


def warm() -> bool:
    """Load the model eagerly when the app warms the voice subsystem."""
    try:
        _load_session()
        return True
    except BOUNDARY_ERRORS:
        return False
