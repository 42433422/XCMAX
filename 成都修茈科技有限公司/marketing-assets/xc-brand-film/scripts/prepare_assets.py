#!/usr/bin/env python3
from __future__ import annotations

import math
import wave
from pathlib import Path

import numpy as np
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
OUTPUT = ROOT / "output"
SAMPLE_RATE = 48_000
DURATION = 18.0


def prepare_logo() -> None:
    source = Image.open(ASSETS / "logo-source.png").convert("RGB")
    rgb = np.asarray(source, dtype=np.float32)
    distance_from_white = 255.0 - rgb.min(axis=2)
    alpha = np.clip((distance_from_white - 6.0) * 2.2, 0.0, 255.0).astype(np.uint8)

    ys, xs = np.where(alpha > 10)
    padding = 22
    box = (
        max(0, int(xs.min()) - padding),
        max(0, int(ys.min()) - padding),
        min(source.width, int(xs.max()) + padding + 1),
        min(source.height, int(ys.max()) + padding + 1),
    )

    alpha = alpha[box[1] : box[3], box[0] : box[2]]
    height, width = alpha.shape
    y = np.linspace(0.0, 1.0, height, dtype=np.float32)[:, None]

    top = np.array([226.0, 247.0, 255.0], dtype=np.float32)
    bottom = np.array([20.0, 181.0, 255.0], dtype=np.float32)
    color = top[None, None, :] * (1.0 - y[:, :, None]) + bottom[None, None, :] * y[:, :, None]
    color = np.broadcast_to(color, (height, width, 3)).astype(np.uint8)

    rgba = np.dstack((color, alpha))
    Image.fromarray(rgba, "RGBA").save(ASSETS / "logo-glow.png")


def smoothstep(x: np.ndarray) -> np.ndarray:
    x = np.clip(x, 0.0, 1.0)
    return x * x * (3.0 - 2.0 * x)


def add_whoosh(track: np.ndarray, start: float, duration: float, strength: float) -> None:
    begin = int(start * SAMPLE_RATE)
    count = min(int(duration * SAMPLE_RATE), len(track) - begin)
    if count <= 0:
        return
    local_t = np.arange(count, dtype=np.float64) / SAMPLE_RATE
    envelope = np.sin(np.pi * local_t / duration) ** 2
    rng = np.random.default_rng(int(start * 10_000) + 73)
    noise = rng.standard_normal(count)
    filtered = np.convolve(noise, np.ones(24) / 24.0, mode="same")
    rising = np.sin(2.0 * np.pi * (180.0 * local_t + 420.0 * local_t**2))
    track[begin : begin + count] += strength * envelope * (0.55 * filtered + 0.45 * rising)


def add_impact(track: np.ndarray, start: float, strength: float) -> None:
    begin = int(start * SAMPLE_RATE)
    count = min(int(1.15 * SAMPLE_RATE), len(track) - begin)
    if count <= 0:
        return
    local_t = np.arange(count, dtype=np.float64) / SAMPLE_RATE
    envelope = np.exp(-4.8 * local_t)
    pitch = 58.0 - 18.0 * np.clip(local_t / 1.15, 0.0, 1.0)
    phase = 2.0 * np.pi * np.cumsum(pitch) / SAMPLE_RATE
    click = np.exp(-38.0 * local_t) * np.sin(2.0 * np.pi * 840.0 * local_t)
    track[begin : begin + count] += strength * (0.84 * envelope * np.sin(phase) + 0.16 * click)


def prepare_audio() -> None:
    sample_count = int(DURATION * SAMPLE_RATE)
    t = np.arange(sample_count, dtype=np.float64) / SAMPLE_RATE

    intro = smoothstep(t / 1.4)
    outro = smoothstep((DURATION - t) / 0.8)
    bed = (
        0.030 * np.sin(2.0 * np.pi * 55.0 * t)
        + 0.014 * np.sin(2.0 * np.pi * 110.0 * t + 0.8)
        + 0.008 * np.sin(2.0 * np.pi * 220.0 * t + 1.9)
    )
    pulse = 0.008 * np.sin(2.0 * np.pi * 2.0 * t) * np.sin(2.0 * np.pi * 330.0 * t)
    mono = (bed + pulse) * intro * outro

    for start, duration, strength in (
        (0.15, 1.9, 0.035),
        (2.45, 0.8, 0.105),
        (6.70, 0.55, 0.080),
        (8.15, 0.24, 0.050),
        (9.50, 0.24, 0.050),
        (10.75, 0.55, 0.075),
        (13.70, 0.75, 0.090),
    ):
        add_whoosh(mono, start, duration, strength)

    for start, strength in ((3.0, 0.11), (7.0, 0.08), (11.0, 0.09), (14.0, 0.12), (17.15, 0.20)):
        add_impact(mono, start, strength)

    peak = max(float(np.abs(mono).max()), 1e-6)
    mono = np.tanh(mono / max(peak, 0.42) * 1.6) * 0.70
    stereo = np.column_stack((mono, mono * 0.985))
    pcm = np.clip(stereo * 32767.0, -32768, 32767).astype("<i2")

    OUTPUT.mkdir(parents=True, exist_ok=True)
    with wave.open(str(OUTPUT / "xc-brand-film-soundtrack.wav"), "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(pcm.tobytes())


def main() -> None:
    prepare_logo()
    prepare_audio()
    print(f"Prepared assets in {ROOT}")


if __name__ == "__main__":
    main()
