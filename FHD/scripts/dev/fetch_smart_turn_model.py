"""Provision the pinned Smart Turn model for source runs and desktop packaging."""

from pathlib import Path

from app.desktop_runtime.model_downloader import ModelAsset, download_model

_MODEL = ModelAsset(
    name="smart-turn",
    version="3.2",
    url=(
        "https://huggingface.co/pipecat-ai/smart-turn-v3/resolve/"
        "f766f81d3cfdf7737ac64aad813d91bbfd56bf93/smart-turn-v3.2-cpu.onnx"
    ),
    sha256="2bb026316b14a660486a75b1733cd3fbab8c2fd0314dc9af7be49f8cca967e4f",
    size=8_679_182,
)


def provision_model() -> Path:
    destination = Path(__file__).resolve().parents[2] / "app/application/voice/models"
    return download_model(_MODEL, destination_dir=destination)


if __name__ == "__main__":
    print(provision_model())
