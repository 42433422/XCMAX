#!/usr/bin/env python3
"""Prepare the pinned official OpenIM Compose distribution on loopback only."""

import argparse
import secrets
import subprocess
from pathlib import Path

import yaml

UPSTREAM = "https://github.com/openimsdk/openim-docker.git"
REVISION = "9b69872983a3a4984dc0b66848831ef69bf202cc"


def prepare(destination: Path) -> None:
    if not destination.exists():
        subprocess.run(
            [
                "git",
                "clone",
                "--depth",
                "1",
                "--branch",
                "v3.8.3-patch.1",
                UPSTREAM,
                str(destination),
            ],
            check=True,
        )
    revision = subprocess.check_output(
        ["git", "-C", str(destination), "rev-parse", "HEAD"], text=True
    ).strip()
    if revision != REVISION:
        raise SystemExit(
            "Destination is not the pinned upstream checkout; preserve it and choose another path."
        )
    compose = yaml.safe_load((destination / "docker-compose.yaml").read_text())
    services = compose["services"] = {
        key: value
        for key, value in compose["services"].items()
        if key in {"mongo", "redis", "etcd", "kafka", "minio", "openim-server"}
    }
    for service in services.values():
        service.pop("container_name", None)
        service.pop("ports", None)
        service["restart"] = "unless-stopped"
    services["openim-server"]["ports"] = ["127.0.0.1:15201:10001", "127.0.0.1:15202:10002"]
    services["minio"]["ports"] = ["127.0.0.1:15205:9000"]
    services["redis"]["volumes"] = ["${DATA_DIR}/components/redis/data:/data"]
    services["redis"]["command"] = [
        "redis-server",
        "--requirepass",
        "${REDIS_PASSWORD}",
        "--appendonly",
        "yes",
    ]
    services["mongo"]["environment"] = [
        value
        if not value.startswith("MONGO_INITDB_ROOT_PASSWORD=")
        else "MONGO_INITDB_ROOT_PASSWORD=${MONGO_PASSWORD}"
        for value in services["mongo"]["environment"]
    ]
    services["mongo"]["command"] = services["mongo"]["command"].replace(
        'print("Password: $$MONGO_OPENIM_PASSWORD");', ""
    )
    (destination / "candidate-compose.yaml").write_text(yaml.safe_dump(compose, sort_keys=False))
    environment = destination / "candidate.env"
    if not environment.exists():
        values = {
            name: secrets.token_hex(24)
            for name in (
                "OPENIM_SECRET",
                "MONGO_PASSWORD",
                "REDIS_PASSWORD",
                "MINIO_SECRET_ACCESS_KEY",
            )
        }
        values.update(
            DATA_DIR=str(destination / "candidate-data"),
            MINIO_EXTERNAL_ADDRESS="http://127.0.0.1:15205",
        )
        lines = [
            line.partition("=")[0] + "=" + values[line.partition("=")[0]]
            if line.partition("=")[0] in values
            else line
            for line in (destination / ".env").read_text().splitlines()
        ]
        with environment.open("x") as stream:
            environment.chmod(0o600)
            stream.write("\n".join(lines) + "\n")
    print(f"Prepared {REVISION}; credentials and existing data retained in {destination}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    prepare(args.destination.resolve())
