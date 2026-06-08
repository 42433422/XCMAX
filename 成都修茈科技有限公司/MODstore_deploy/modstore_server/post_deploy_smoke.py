"""Post-deploy HTTP smoke: MODstore health + public market download page.

Used after ``approval_dispatcher.deploy_staged_change`` and optional scheduler interval.
URLs from env (no secrets required for public HTTPS probes).
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)

_DEFAULT_HEALTH = "http://127.0.0.1:9999/api/health"
_DEFAULT_MARKET = "https://xiu-ci.com/market/download"


def _state_file_path() -> Path:
    raw = (
        os.environ.get("MODSTORE_POST_DEPLOY_SMOKE_STATE_FILE")
        or "playwright-report/post-deploy-smoke-last.json"
    ).strip()
    try:
        from modstore_server.daily_digest import _repo_root

        root = Path(_repo_root())
    except Exception:
        root = Path(os.environ.get("MODSTORE_REPO_ROOT", ".")).resolve()
    return root / raw


def _persist_last_result(payload: Dict[str, Any]) -> None:
    try:
        path = _state_file_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        logger.exception("post_deploy_smoke: persist last result failed")


def load_last_smoke_result() -> Dict[str, Any]:
    """Read last probe outcome written by ``run_post_deploy_smoke``."""
    path = _state_file_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def slo_halt_blocks_auto_merge() -> bool:
    """When ``MODSTORE_SLO_HALT_AUTO_MERGE=1`` and last smoke failed, block auto-merge/deploy."""
    enabled = (os.environ.get("MODSTORE_SLO_HALT_AUTO_MERGE", "0") or "").strip().lower()
    if enabled not in ("1", "true", "yes", "on"):
        return False
    last = load_last_smoke_result()
    if last.get("skipped"):
        return False
    if not last:
        return False
    return not bool(last.get("ok"))


def _probe_urls() -> List[Tuple[str, str]]:
    health = (os.environ.get("MODSTORE_DEPLOY_HEALTH_URL") or _DEFAULT_HEALTH).strip()
    market = (os.environ.get("MODSTORE_POST_DEPLOY_MARKET_URL") or _DEFAULT_MARKET).strip()
    out: List[Tuple[str, str]] = []
    if health:
        out.append(("health", health))
    if market:
        out.append(("market_download", market))
    return out


def _http_get_status(url: str, *, timeout_sec: float) -> Tuple[int, str]:
    req = urllib.request.Request(
        url, method="GET", headers={"User-Agent": "MODstore-post-deploy-smoke/1.0"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            return int(resp.status), ""
    except urllib.error.HTTPError as exc:
        return int(exc.code), str(exc.reason or exc)
    except Exception as exc:  # noqa: BLE001
        return 0, str(exc)


def run_post_deploy_smoke(*, timeout_sec: float | None = None) -> Dict[str, Any]:
    """Probe configured URLs; expect HTTP 2xx."""
    enabled = (os.environ.get("MODSTORE_POST_DEPLOY_SMOKE_ENABLED", "1") or "").strip().lower()
    if enabled in ("0", "false", "no", "off"):
        return {"ok": True, "skipped": True, "probes": []}

    try:
        timeout = float(
            timeout_sec
            if timeout_sec is not None
            else os.environ.get("MODSTORE_POST_DEPLOY_SMOKE_TIMEOUT_SEC", "15")
        )
    except ValueError:
        timeout = 15.0
    timeout = max(3.0, min(timeout, 60.0))

    probes: List[Dict[str, Any]] = []
    ok = True
    t0 = time.perf_counter()
    for name, url in _probe_urls():
        status, err = _http_get_status(url, timeout_sec=timeout)
        row = {"name": name, "url": url, "status": status, "error": err}
        if status < 200 or status >= 400:
            row["ok"] = False
            ok = False
        else:
            row["ok"] = True
        probes.append(row)
        logger.info("post_deploy_smoke %s %s status=%s ok=%s", name, url, status, row["ok"])

    result = {
        "ok": ok and bool(probes),
        "skipped": False,
        "probes": probes,
        "duration_ms": round((time.perf_counter() - t0) * 1000, 1),
        "ran_at": datetime.now(timezone.utc).isoformat(),
    }
    _persist_last_result(result)
    return result
