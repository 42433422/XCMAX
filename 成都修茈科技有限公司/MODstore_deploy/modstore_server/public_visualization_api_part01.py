# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("modstore_server.public_visualization_api")


def _positive_int_env(name: str, default: int, *, maximum: int) -> int:
    try:
        value = int((_facade().os.environ.get(name) or "").strip())
    except ValueError:
        return default
    if value <= 0:
        return default
    return min(value, maximum)


def _cache_ttl_seconds() -> int:
    return _facade()._positive_int_env(
        "XIUCI_VISUALIZATION_CACHE_TTL_SECONDS",
        _facade()._DEFAULT_CACHE_TTL_SECONDS,
        maximum=300,
    )


def _trend_days() -> int:
    return _facade()._positive_int_env(
        "XIUCI_VISUALIZATION_TREND_DAYS", _facade()._DEFAULT_TREND_DAYS, maximum=31
    )


def _release_manifest_path() -> _facade().Path:
    configured = (_facade().os.environ.get("XIUCI_VISUALIZATION_RELEASE_MANIFEST") or "").strip()
    if configured:
        return _facade().Path(configured).expanduser()
    site_root = _facade().Path(__file__).resolve().parents[2]
    candidates = (
        site_root / "download-release.json",
        site_root.parent / "FHD" / "config" / "download_release.json",
    )
    for path in candidates:
        try:
            raw = _facade().json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, _facade().json.JSONDecodeError):
            continue
        if (
            isinstance(raw, dict)
            and isinstance(raw.get("release_history"), list)
            and raw["release_history"]
        ):
            return path
    return candidates[0]


def _access_log_paths() -> list[_facade().Path]:
    pattern = (_facade().os.environ.get("XIUCI_VISUALIZATION_ACCESS_LOG_GLOB") or "").strip()
    matches = _facade().glob.glob(pattern or _facade()._DEFAULT_LOG_GLOB)
    return sorted(
        (_facade().Path(match) for match in matches if _facade().Path(match).is_file()),
        key=str,
    )


def _open_log(path: _facade().Path) -> _facade().TextIO:
    if path.suffix == ".gz":
        return _facade().gzip.open(path, "rt", encoding="utf-8", errors="replace")
    return path.open("r", encoding="utf-8", errors="replace")


def _parse_log_date(stamp: str) -> _facade().date | None:
    match = _facade()._STAMP_DATE_RE.match(stamp)
    if not match:
        return None
    month = _facade()._MONTHS.get(match.group("month"))
    if month is None:
        return None
    try:
        return _facade().date(int(match.group("year")), month, int(match.group("day")))
    except ValueError:
        return None


def _short_date(value: _facade().date | None) -> str | None:
    return value.strftime("%m.%d") if value is not None else None


def _iso_date(value: _facade().date | None) -> str | None:
    return value.isoformat() if value is not None else None


def _empty_traffic_metrics() -> tuple[dict[str, _facade().Any], dict[str, _facade().Any]]:
    return (
        {
            "chat_requests": None,
            "chat_success": None,
            "success_rate": None,
            "window_start": None,
            "window_end": None,
            "window_start_short": None,
            "window_end_short": None,
        },
        {
            "total": None,
            "platforms": {"windows": None, "macos": None, "android": None},
            "products": {"xcagi": None, "kellai": None},
            "daily": [],
            "window_start": None,
            "window_end": None,
            "window_start_short": None,
            "window_end_short": None,
        },
    )


def _read_traffic_metrics(
    paths: list[_facade().Path],
) -> tuple[dict[str, _facade().Any], dict[str, _facade().Any], dict[str, _facade().Any]]:
    ai_total = 0
    ai_success = 0
    api_requests = 0
    api_5xx = 0
    mod_requests = 0
    downloads_total = 0
    download_platforms: _facade().Counter[str] = _facade().Counter()
    download_products: _facade().Counter[str] = _facade().Counter()
    download_daily: _facade().Counter[_facade().date] = _facade().Counter()
    retained_start: _facade().date | None = None
    retained_end: _facade().date | None = None
    parsed_lines = 0
    unreadable_files = 0
    source_mtime = 0.0
    for path in paths:
        try:
            source_mtime = max(source_mtime, path.stat().st_mtime)
            with _facade()._open_log(path) as handle:
                for line in handle:
                    match = _facade()._LOG_RE.match(line)
                    if not match:
                        continue
                    request_date = _facade()._parse_log_date(match.group("stamp"))
                    if request_date is None:
                        continue
                    parsed_lines += 1
                    retained_start = (
                        request_date
                        if retained_start is None
                        else min(retained_start, request_date)
                    )
                    retained_end = (
                        request_date if retained_end is None else max(retained_end, request_date)
                    )
                    method = match.group("method")
                    status = int(match.group("status"))
                    target = _facade().unquote(match.group("target").partition("?")[0])
                    target_lower = target.lower()
                    if target.startswith("/api/"):
                        api_requests += 1
                        if 500 <= status <= 599:
                            api_5xx += 1
                        if target_lower.startswith(("/api/mod-store", "/api/mods")):
                            mod_requests += 1
                    if method == "POST" and target == "/api/llm/chat/stream":
                        ai_total += 1
                        if status == 200:
                            ai_success += 1
                    if method != "GET" or status != 200:
                        continue
                    if not target_lower.startswith(_facade()._DOWNLOAD_PREFIXES):
                        continue
                    platform = next(
                        (
                            name
                            for (
                                suffix,
                                name,
                            ) in _facade()._DOWNLOAD_PLATFORM_BY_SUFFIX.items()
                            if target_lower.endswith(suffix)
                        ),
                        None,
                    )
                    if platform is None:
                        continue
                    downloads_total += 1
                    download_platforms[platform] += 1
                    product = "kellai" if target_lower.startswith("/downloads/kellai/") else "xcagi"
                    download_products[product] += 1
                    download_daily[request_date] += 1
        except (OSError, EOFError):
            unreadable_files += 1
    if parsed_lines == 0:
        ai, downloads = _facade()._empty_traffic_metrics()
        return (
            ai,
            downloads,
            {
                "status": "unavailable",
                "files_scanned": len(paths),
                "files_unreadable": unreadable_files,
                "parsed_lines": 0,
                "source_updated_at": None,
                "api_requests": 0,
                "api_5xx": 0,
                "mod_requests": 0,
            },
        )
    ai_rate = round(ai_success / ai_total * 100, 2) if ai_total else 0.0
    ai = {
        "chat_requests": ai_total,
        "chat_success": ai_success,
        "success_rate": ai_rate,
        "window_start": _facade()._iso_date(retained_start),
        "window_end": _facade()._iso_date(retained_end),
        "window_start_short": _facade()._short_date(retained_start),
        "window_end_short": _facade()._short_date(retained_end),
    }
    daily: list[dict[str, _facade().Any]] = []
    if retained_end is not None:
        first_day = retained_end - _facade().timedelta(days=_facade()._trend_days() - 1)
        for offset in range(_facade()._trend_days()):
            day = first_day + _facade().timedelta(days=offset)
            daily.append(
                {
                    "date": _facade()._short_date(day),
                    "iso_date": day.isoformat(),
                    "count": download_daily[day],
                }
            )
    downloads = {
        "total": downloads_total,
        "platforms": {
            "windows": download_platforms["windows"],
            "macos": download_platforms["macos"],
            "android": download_platforms["android"],
        },
        "products": {
            "xcagi": download_products["xcagi"],
            "kellai": download_products["kellai"],
        },
        "daily": daily,
        "window_start": _facade()._iso_date(retained_start),
        "window_end": _facade()._iso_date(retained_end),
        "window_start_short": _facade()._short_date(retained_start),
        "window_end_short": _facade()._short_date(retained_end),
    }
    source_updated_at = (
        _facade()
        .datetime.fromtimestamp(source_mtime, tz=_facade()._SHANGHAI)
        .isoformat(timespec="seconds")
        if source_mtime
        else None
    )
    source_status = "live" if unreadable_files == 0 else "degraded"
    return (
        ai,
        downloads,
        {
            "status": source_status,
            "files_scanned": len(paths),
            "files_unreadable": unreadable_files,
            "parsed_lines": parsed_lines,
            "source_updated_at": source_updated_at,
            "api_requests": api_requests,
            "api_5xx": api_5xx,
            "mod_requests": mod_requests,
            "window_days": (
                (retained_end - retained_start).days + 1
                if retained_start and retained_end
                else None
            ),
        },
    )


def _prometheus_base_url() -> str:
    return (
        _facade().os.environ.get("XIUCI_VISUALIZATION_PROMETHEUS_URL") or "http://127.0.0.1:9090"
    ).rstrip("/")


def _prometheus_job() -> str:
    return (
        _facade().os.environ.get("XIUCI_VISUALIZATION_PROM_JOB") or "xcagi-backend"
    ).strip() or "xcagi-backend"


def _prom_instant(expr: str) -> float | None:
    url = f"{_facade()._prometheus_base_url()}/api/v1/query?query={_facade().quote(expr)}"
    request = _facade().Request(url, headers={"Accept": "application/json"})
    try:
        with _facade().urlopen(request, timeout=0.8) as response:
            payload = _facade().json.loads(response.read().decode("utf-8", errors="replace"))
    except (
        _facade().HTTPError,
        _facade().URLError,
        TimeoutError,
        OSError,
        ValueError,
        _facade().json.JSONDecodeError,
    ):
        return None
    if not isinstance(payload, dict) or payload.get("status") != "success":
        return None
    result = (
        (payload.get("data") or {}).get("result") if isinstance(payload.get("data"), dict) else None
    )
    if not isinstance(result, list) or not result:
        return None
    try:
        value = float(result[0]["value"][1])
    except (KeyError, TypeError, ValueError, IndexError):
        return None
    return value if value == value else None
