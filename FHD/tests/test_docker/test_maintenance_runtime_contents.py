"""Check the production COPY surface, not imports from the full source checkout."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

FHD_ROOT = Path(__file__).resolve().parents[2]


def test_image_can_register_admin_maintenance_without_source_checkout(tmp_path: Path) -> None:
    image = tmp_path / "image"
    dockerfile = (FHD_ROOT / "ops/docker/Dockerfile.fhd-api").read_text()
    production = dockerfile.split(" AS production", 1)[1]
    for line in production.splitlines():
        if not line.startswith("COPY "):
            continue
        tokens = [token for token in shlex.split(line)[1:] if not token.startswith("--")]
        # Route registration also imports resources and managed package sources.
        # Reproduce those existing production COPY directives in the isolated image.
        if len(tokens) == 2 and tokens[0] in {"app", "resources", "packages", "XCAGI"}:
            assert tokens[1] == f"/app/{tokens[0]}"
            shutil.copytree(
                FHD_ROOT / tokens[0],
                image / tokens[0],
                ignore=shutil.ignore_patterns("__pycache__"),
            )
            continue
        if tokens[-1] != "/app/scripts/autonomy/":
            continue
        target = image / "scripts/autonomy"
        target.mkdir(parents=True)
        for source in tokens[:-1]:
            shutil.copy2(FHD_ROOT / source, target / Path(source).name)
    env = {**os.environ, "XCAGI_DATA_DIR": str(tmp_path / "data")}
    env["XCAGI_DESKTOP_DATA_DIR"] = env["XCAGI_DATA_DIR"]
    env["DATABASE_URL"] = f"sqlite:///{tmp_path / 'runtime.db'}"
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            "import sys; sys.path.insert(0, sys.argv[1]); "
            "import app.fastapi_routes.xcmax_admin as routes; "
            "assert routes._autonomy; "
            "from scripts.autonomy import rundeck_executor; "
            "assert rundeck_executor.REMOTE_ACTIONS",
            str(image),
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
