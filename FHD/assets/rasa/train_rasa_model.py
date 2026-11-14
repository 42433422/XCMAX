"""Train the optional Rasa NLU model with an explicitly supplied local corpus."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

RASA_DIR = Path(__file__).resolve().parent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=RASA_DIR / "config.yml")
    parser.add_argument("--data", type=Path, default=RASA_DIR / "data" / "nlu.yml")
    parser.add_argument("--output", type=Path, default=RASA_DIR / "models")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    config, data, output = (p.expanduser().resolve() for p in (args.config, args.data, args.output))
    for label, path in (("配置", config), ("训练数据", data)):
        if not path.is_file():
            parser.error(f"{label}不存在: {path}；训练数据由调用方通过 --data 提供")
    command = [
        sys.executable,
        "-m",
        "rasa",
        "train",
        "nlu",
        "--config",
        str(config),
        "--nlu",
        str(data),
        "--output",
        str(output),
    ]
    if args.force:
        command.append("--force")
    try:
        output.mkdir(parents=True, exist_ok=True)
        return subprocess.run(command, cwd=RASA_DIR.parent, check=False).returncode
    except OSError as exc:
        print(f"无法启动 Rasa 训练: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
