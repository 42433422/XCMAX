# ruff: noqa: E402, F401
"""Privacy-safe public aggregates for the official visualization page.

The endpoint deliberately reads the same production artefacts that operators
use to verify releases: Nginx access logs for traffic and the public release
manifest for product delivery state.  It never returns request paths, client
addresses, account data, or conversation content.
"""

from __future__ import annotations

import copy
import glob
import gzip
import json
import os
import re
import threading
import time
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, TextIO
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Response
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

router = APIRouter(tags=["public-data"])

_DEFAULT_LOG_GLOB = "/var/log/nginx/xiu-ci.com.access.log*"
_DEFAULT_CACHE_TTL_SECONDS = 30
_DEFAULT_TREND_DAYS = 10
_SHANGHAI = ZoneInfo("Asia/Shanghai")
_MONTHS = {
    "Jan": 1,
    "Feb": 2,
    "Mar": 3,
    "Apr": 4,
    "May": 5,
    "Jun": 6,
    "Jul": 7,
    "Aug": 8,
    "Sep": 9,
    "Oct": 10,
    "Nov": 11,
    "Dec": 12,
}
_LOG_RE = re.compile(
    r"^\S+\s+\S+\s+\S+\s+\[(?P<stamp>[^\]]+)\]\s+"
    r'"(?P<method>[A-Z]+)\s+(?P<target>\S+)\s+HTTP/[^\"]+"\s+'
    r"(?P<status>\d{3})\s+\S+"
)
_STAMP_DATE_RE = re.compile(r"^(?P<day>\d{2})/(?P<month>[A-Z][a-z]{2})/(?P<year>\d{4}):")
_DOWNLOAD_PREFIXES = ("/xcagi-v", "/releases/stable/", "/downloads/kellai/")
_DOWNLOAD_PLATFORM_BY_SUFFIX = {
    ".exe": "windows",
    ".dmg": "macos",
    ".apk": "android",
}

_CACHE_LOCK = threading.Lock()
_CACHE_VALUE: dict[str, Any] | None = None
_CACHE_CREATED_MONOTONIC = 0.0


from modstore_server.public_visualization_api_part01 import (
    _positive_int_env as _positive_int_env,
    _cache_ttl_seconds as _cache_ttl_seconds,
    _trend_days as _trend_days,
    _release_manifest_path as _release_manifest_path,
    _access_log_paths as _access_log_paths,
    _open_log as _open_log,
    _parse_log_date as _parse_log_date,
    _short_date as _short_date,
    _iso_date as _iso_date,
    _empty_traffic_metrics as _empty_traffic_metrics,
    _read_traffic_metrics as _read_traffic_metrics,
    _prometheus_base_url as _prometheus_base_url,
    _prometheus_job as _prometheus_job,
    _prom_instant as _prom_instant,
)


_METRIC_LINE_RE = re.compile(
    r"^(?P<name>[a-zA-Z_:][a-zA-Z0-9_:]*)(?:\{(?P<labels>[^}]*)\})?\s+(?P<value>[-+0-9.eE]+)\s*$"
)
_LABEL_RE = re.compile(r'([a-zA-Z_][a-zA-Z0-9_]*)="((?:\\.|[^"\\])*)"')


from modstore_server.public_visualization_api_part02 import (
    _metrics_base_url as _metrics_base_url,
    _parse_metric_labels as _parse_metric_labels,
    _scrape_app_metrics as _scrape_app_metrics,
    _bus_runtime_metrics as _bus_runtime_metrics,
    _host_infra_metrics as _host_infra_metrics,
    _panel as _panel,
    _fmt_num as _fmt_num,
    _coalesce as _coalesce,
    _build_monitor_payload as _build_monitor_payload,
    _read_product_metrics as _read_product_metrics,
    _token_engine as _token_engine,
    _as_shanghai_datetime as _as_shanghai_datetime,
    _platform_made_snapshot_candidates as _platform_made_snapshot_candidates,
    _platform_made_snapshot_path as _platform_made_snapshot_path,
    _empty_made_token_metrics as _empty_made_token_metrics,
    _read_platform_made_metrics as _read_platform_made_metrics,
    _empty_token_metrics as _empty_token_metrics,
    _read_token_metrics as _read_token_metrics,
    _build_public_visualization_data as _build_public_visualization_data,
    clear_public_visualization_cache as clear_public_visualization_cache,
)


from modstore_server.public_visualization_api_part03 import (
    get_public_visualization_data as get_public_visualization_data,
    public_visualization as public_visualization,
)
