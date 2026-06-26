#!/usr/bin/env python3
"""日更闭环冒烟：备份 / DR 探针 / 归档 / 按需快照 / 可选 digest。"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def _load_env() -> None:
    candidates = [Path.cwd(), Path(__file__).resolve().parents[1]]
    try:
        from dotenv import load_dotenv

        for root in candidates:
            env = root / ".env"
            if env.is_file():
                load_dotenv(env)
                break
    except Exception:
        pass
    os.environ.setdefault("PYTHONUTF8", "1")


def run_smoke(*, with_digest: bool = False) -> dict:
    _load_env()
    out: dict = {}

    from modstore_server.daily_backup_job import run_daily_backup_job

    bk = run_daily_backup_job()
    out["backup"] = {"ok": bk.get("ok"), "stamp": bk.get("stamp")}

    from modstore_server.dr_recovery_probe_job import run_dr_recovery_probe

    out["dr_probe"] = run_dr_recovery_probe()

    from modstore_server.file_retention_janitor import run_retention_janitor

    out["retention_dry_run"] = {"ok": run_retention_janitor(dry_run=True).get("ok")}

    from modstore_server.ondemand_backup import run_ondemand_backup

    out["ondemand"] = {"ok": run_ondemand_backup(trigger="verify_smoke").get("ok")}

    out["env"] = {
        "digest_mode": os.environ.get("MODSTORE_DAILY_ORCHESTRATOR_DIGEST_MODE"),
        "cr_git_auto_pr": os.environ.get("MODSTORE_CR_GIT_AUTO_PR"),
        "auto_approve": os.environ.get("MODSTORE_OPS_STAGED_AUTO_APPROVE"),
        "digest_enabled": os.environ.get("MODSTORE_DAILY_DIGEST_ENABLED"),
        "repo_root": os.environ.get("MODSTORE_REPO_ROOT"),
    }

    if with_digest:
        from modstore_server.daily_digest import run_daily_digest_email

        try:
            run_daily_digest_email()
            out["digest"] = {"ok": True, "triggered": True}
        except Exception as exc:  # noqa: BLE001
            out["digest"] = {"ok": False, "error": str(exc)[:500]}

    out["ok"] = bool(out["backup"].get("ok")) and bool(out["retention_dry_run"].get("ok"))
    return out


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--digest", action="store_true", help="also run run_daily_digest_email")
    args = p.parse_args()
    result = run_smoke(with_digest=args.digest)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
