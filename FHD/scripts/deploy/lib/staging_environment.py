"""Derive isolated systemd settings without executing the production env file."""

from __future__ import annotations

import json
import os
import shlex
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit, urlunsplit


def render(source: str, *, root: str, port: int, data_root: str) -> str:
    lines = source.splitlines()
    values = {}
    for line in lines:
        if line.strip() and not line.lstrip().startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()

    def decoded(key: str) -> str:
        parts = shlex.split(values.get(key, ""), comments=True)
        if len(parts) > 1:
            raise ValueError(f"invalid staging source setting: {key}")
        return parts[0] if parts else ""

    if not 1024 <= port <= 65535 or port == int(decoded("XCAGI_API_PORT") or 5100):
        raise ValueError("staging API port must be distinct from production")
    root_path = Path(root).resolve()
    production_root = Path(decoded("WORKSPACE_ROOT") or "/opt/fhd-full").resolve()
    if (
        root_path == production_root
        or production_root in root_path.parents
        or root_path in production_root.parents
    ):
        raise ValueError("staging release root overlaps production")
    isolated_data = Path(data_root).resolve()
    for key in ("XCAGI_DATA_DIR", "XCAGI_DESKTOP_DATA_DIR", "DATABASE_PATH", "UPLOAD_FOLDER"):
        previous = decoded(key)
        if previous:
            production_data = Path(previous).resolve()
            if (
                production_data == isolated_data
                or production_data in isolated_data.parents
                or isolated_data in production_data.parents
            ):
                raise ValueError("staging data directory overlaps production")

    database = urlsplit(decoded("DATABASE_URL"))
    if (
        database.scheme
        not in {"postgresql", "postgresql+psycopg", "postgresql+psycopg2", "postgresql+asyncpg"}
        or not database.netloc
        or database.path != "/xcagi"
    ):
        raise ValueError("staging bootstrap requires the configured xcagi PostgreSQL source")
    staging_database = urlunsplit(database._replace(path="/xcagi_staging"))
    replacements = {
        "DATABASE_URL": staging_database,
        "VECTOR_DB_URL": staging_database,
        "XCAGI_API_PORT": str(port),
        "XCAGI_ENV": "staging",
        "MODSTORE_DEPLOY_TIER": "staging",
        "FHD_DEPLOY_TIER": "staging",
        "XCAGI_AUTONOMY_DATA_DIR": str(isolated_data / "autonomy"),
        "XCAGI_DATA_DIR": str(isolated_data),
        "XCAGI_DESKTOP_DATA_DIR": str(isolated_data),
        "DATABASE_PATH": str(isolated_data),
        "UPLOAD_FOLDER": str(isolated_data / "uploads"),
        "XCAGI_MODS_ROOT": str(root_path / "mods"),
        "WORKSPACE_ROOT": str(root_path),
        "XCMAX_MONOREPO_ROOT": str(root_path),
    }
    # Subsequent staging updates must read their own immutable package/stamps.
    for key in (
        "XCAGI_GIT_SHA",
        "FHD_GIT_SHA",
        "GIT_SHA",
        "XCAGI_IMAGE_DIGEST",
        "FHD_API_IMAGE_DIGEST",
        "XCAGI_ARTIFACT_SHA256",
        "XCMAX_PRODUCT_VERSION",
        "XCAGI_RELEASE_ID",
        "XCAGI_ADMIN_CONSOLE_SHA256",
        "FHD_ADMIN_CONSOLE_SHA256",
    ):
        replacements[key] = ""
    for key in ("CACHE_REDIS_URL", "REDIS_URL", "CELERY_BROKER_URL", "CELERY_RESULT_BACKEND"):
        previous = decoded(key)
        if not previous:
            continue
        isolated = os.environ.get("FHD_STAGING_" + key, "").strip()
        if not isolated or isolated == previous:
            raise ValueError(f"FHD_STAGING_{key} must identify an isolated staging backend")
        old_url, new_url = urlsplit(previous), urlsplit(isolated)

        def backend(url):
            db = parse_qs(url.query).get("db", [url.path.strip("/") or "0"])[0]
            return url.hostname, url.port or 6379, int(db)

        if backend(old_url) == backend(new_url):
            raise ValueError(f"staging backend still targets production: {key}")
        if new_url.scheme not in {"redis", "rediss"} or not new_url.hostname:
            raise ValueError(f"invalid staging backend: {key}")
        replacements[key] = isolated
    for suffix in ("DEDUP", "CIRCUIT", "RATE_LIMIT", "TRACE", "LIFELINE", "DLQ_AUTO", "SLA_LOG"):
        replacements[f"XCAGI_NEURO_BUS_{suffix}"] = "1"
    retained = [line for line in lines if line.split("=", 1)[0].strip() not in replacements]
    retained.extend(f"{key}={json.dumps(value)}" for key, value in replacements.items())
    return "\n".join(retained) + "\n"


def main() -> None:
    source, target, root, port, data_root = sys.argv[1:]
    if Path(source).resolve() == Path(target).resolve():
        raise ValueError("staging settings cannot overwrite production settings")
    output = render(Path(source).read_text(), root=root, port=int(port), data_root=data_root)
    destination = Path(target)
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write(output)


if __name__ == "__main__":
    main()
