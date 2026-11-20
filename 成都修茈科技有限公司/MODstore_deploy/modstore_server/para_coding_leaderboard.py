"""Read the Coding column from the current public LiveBench 2.0 release."""

from __future__ import annotations

import csv
import re
import time
from datetime import UTC, datetime
from functools import lru_cache
from io import StringIO

import httpx

ORIGIN = "https://livebench.ai"
ENTRYPOINT = re.compile(r"""src=["'](?:\./|/)?(static/js/main\.[0-9a-f]{8,32}\.js)["']""")
RELEASE_LIST = re.compile(r'\[\s*"(20[0-9]{6})"(?:\s*,\s*"20[0-9]{6}")+\s*\]')
CACHE_SECONDS = 6 * 3600


def _text(client: httpx.Client, path: str) -> str:
    body = bytearray()
    with client.stream("GET", ORIGIN + "/" + path) as response:
        response.raise_for_status()
        for chunk in response.iter_bytes():
            body.extend(chunk)
            if len(body) > 1_000_000:
                raise ValueError("LiveBench asset exceeds size limit")
    return body.decode("utf-8-sig")


def _parse_scores(body: str) -> dict[str, float]:
    rows = csv.DictReader(StringIO(body))
    if not rows.fieldnames or not {"model", "coding"}.issubset(rows.fieldnames):
        raise ValueError("LiveBench Coding columns unavailable")
    scores: dict[str, float] = {}
    for row in rows:
        model = (row.get("model") or "").strip()
        try:
            score = float(row.get("coding") or "")
        except ValueError:
            continue
        if model and 0 <= score <= 100:
            if model in scores:
                raise ValueError("ambiguous LiveBench model identifier")
            scores[model] = score
    if not scores:
        raise ValueError("LiveBench Coding scores unavailable")
    return scores


@lru_cache(maxsize=2)
def _fetch_release(_refresh_slot: int) -> tuple[str, dict[str, float]] | None:
    try:
        with httpx.Client(timeout=3, follow_redirects=False) as client:
            entry = ENTRYPOINT.search(_text(client, ""))
            if not entry:
                return None
            script = _text(client, entry.group(1))
            today = datetime.now(UTC).strftime("%Y%m%d")
            releases = {
                day
                for series in RELEASE_LIST.finditer(script)
                for day in re.findall(r"20[0-9]{6}", series.group())
                if "20261014" <= day <= today
            }
            if not releases:
                return None
            latest = max(releases)
            return latest, _parse_scores(_text(client, f"data/{latest}/table.csv"))
    except (csv.Error, httpx.HTTPError, ValueError):
        return None


def current_coding_scores() -> tuple[str, dict[str, float]] | None:
    return _fetch_release(int(time.time()) // CACHE_SECONDS)
