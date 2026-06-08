#!/usr/bin/env python3
"""Create MODstore Docker Compose backups."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run_to_file(command: list[str], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("wb") as handle:
        proc = subprocess.run(command, cwd=ROOT, stdout=handle, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        message = proc.stderr.decode("utf-8", errors="replace")
        raise RuntimeError(f"{' '.join(command)} failed: {message}")


def run(command: list[str]) -> None:
    proc = subprocess.run(command, cwd=ROOT)
    if proc.returncode != 0:
        raise RuntimeError(f"{' '.join(command)} failed with exit code {proc.returncode}")


def compose_service_running(service: str) -> bool:
    proc = subprocess.run(
        ["docker", "compose", "ps", "-q", service],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    return proc.returncode == 0 and bool(proc.stdout.strip())


# 需 exec 进容器打 tar 的组件：若对应服务未启动则跳过（常见于仅起 db/redis 时先部署 api）
_COMPONENT_SERVICE: dict[str, str] = {
    "modstore_data": "api",
    "prometheus": "prometheus",
    "grafana": "grafana",
}


def docker_tar(service: str, container_path: str, output: Path) -> None:
    parent = str(Path(container_path).parent)
    name = Path(container_path).name
    run_to_file(
        ["docker", "compose", "exec", "-T", service, "tar", "czf", "-", "-C", parent, name],
        output,
    )


def backup_postgres(output_dir: Path) -> Path:
    db = os.environ.get("POSTGRES_DB", "modstore")
    user = os.environ.get("POSTGRES_USER", "modstore")
    output = output_dir / "postgres.dump"
    run_to_file(
        ["docker", "compose", "exec", "-T", "postgres", "pg_dump", "-Fc", "-U", user, "-d", db],
        output,
    )
    return output


def backup_redis(output_dir: Path) -> Path:
    password = os.environ.get("REDIS_PASSWORD", "modstore-redis")
    run(["docker", "compose", "exec", "-T", "redis", "redis-cli", "-a", password, "SAVE"])
    output = output_dir / "redis-data.tar.gz"
    docker_tar("redis", "/data", output)
    return output


def backup_rabbitmq(output_dir: Path) -> Path:
    output = output_dir / "rabbitmq-data.tar.gz"
    docker_tar("rabbitmq", "/var/lib/rabbitmq", output)
    return output


def backup_modstore_data(output_dir: Path) -> Path:
    output = output_dir / "modstore-data.tar.gz"
    docker_tar("api", "/data", output)
    return output


def backup_prometheus(output_dir: Path) -> Path:
    output = output_dir / "prometheus-data.tar.gz"
    docker_tar("prometheus", "/prometheus", output)
    return output


def backup_grafana(output_dir: Path) -> Path:
    output = output_dir / "grafana-data.tar.gz"
    docker_tar("grafana", "/var/lib/grafana", output)
    return output


BACKUP_COMPONENTS = {
    "postgres": backup_postgres,
    "redis": backup_redis,
    "rabbitmq": backup_rabbitmq,
    "modstore_data": backup_modstore_data,
    "prometheus": backup_prometheus,
    "grafana": backup_grafana,
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Back up MODstore compose state.")
    parser.add_argument("--output-dir", default="", help="Backup output directory")
    parser.add_argument(
        "--components",
        default=",".join(BACKUP_COMPONENTS),
        help="Comma separated components: " + ",".join(BACKUP_COMPONENTS),
    )
    args = parser.parse_args()

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir = Path(args.output_dir) if args.output_dir else ROOT / "backups" / timestamp
    output_dir.mkdir(parents=True, exist_ok=True)

    selected = [item.strip() for item in args.components.split(",") if item.strip()]
    unknown = [item for item in selected if item not in BACKUP_COMPONENTS]
    if unknown:
        raise SystemExit(f"Unknown components: {', '.join(unknown)}")

    manifest: dict[str, object] = {
        "created_at": timestamp,
        "root": str(ROOT),
        "components": {},
    }
    for component in selected:
        print(f"Backing up {component}...")
        need_svc = _COMPONENT_SERVICE.get(component)
        if need_svc and not compose_service_running(need_svc):
            print(
                f"Skipping {component}: compose service {need_svc!r} is not running",
                flush=True,
            )
            manifest["components"][component] = {
                "skipped": True,
                "reason": f"service {need_svc} not running",
            }
            continue
        path = BACKUP_COMPONENTS[component](output_dir)
        manifest["components"][component] = {
            "file": path.name,
            "size_bytes": path.stat().st_size,
        }

    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Backup complete: {output_dir}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"backup failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
