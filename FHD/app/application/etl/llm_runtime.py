"""Process-local ETL LLM budgets, cache, and circuit breaker."""

from __future__ import annotations

from app.utils.mixin_module_sync import sync_module_functions


def etl_llm_mode() -> str:
    raw = str(os.environ.get("FHD_ETL_LLM") or "auto").strip().lower()
    if raw in {"0", "false", "no", "off", "disabled"}:
        return "off"
    if raw in {"1", "true", "yes", "on", "enabled"}:
        return "on"
    return "auto"


def etl_llm_timeout_seconds() -> float:
    """Return the hard latency budget for evidence-bound ETL understanding.

    Account-backed model routing includes remote route resolution, billing and
    structured generation.  A six-second budget is shorter than a normal
    successful account request, so it silently removes the semantic stage from
    real previews.  Keep the budget bounded and configurable while allowing the
    primary document-understanding request enough time to finish.
    """

    raw = str(os.environ.get("FHD_ETL_LLM_TIMEOUT") or "30").strip()
    try:
        return min(90.0, max(3.0, float(raw)))
    except ValueError:
        return 30.0


def etl_document_timeout_seconds(evidence: dict[str, Any]) -> float:
    """Return a bounded budget for one workbook-understanding batch.

    Account-backed routing has a material fixed latency before generation
    starts.  A sheet-count-only budget made a compact four-sheet batch time out
    sooner than the previous whole-workbook request even though the batch was
    healthy.  Keep a production-observed floor, then add bounded evidence cost.
    """

    sheets = len(evidence.get("sheets") or [])
    cells = len(evidence.get("cell_index") or {})
    computed = min(
        180.0,
        max(
            120.0,
            105.0 + max(0, sheets - 1) * 5.0 + min(30.0, cells / 75.0),
        ),
    )
    raw = str(os.environ.get("FHD_ETL_LLM_DOCUMENT_TIMEOUT") or computed).strip()
    try:
        return min(180.0, max(10.0, float(raw)))
    except ValueError:
        return computed


def etl_row_advice_limit() -> int:
    raw = str(os.environ.get("FHD_ETL_LLM_ROW_ADVICE_LIMIT") or "20").strip()
    try:
        return min(100, max(0, int(raw)))
    except ValueError:
        return 20


def _degradation_code(exc: BaseException) -> str:
    if type(exc).__name__ == "StructuredOutputError":
        return "ETL_LLM_OUTPUT_INVALID"
    message = str(exc).lower()
    if "quota exhausted" in message or "额度" in message or "429" in message:
        return "ETL_LLM_QUOTA_EXHAUSTED"
    return "ETL_LLM_UNAVAILABLE"


def _circuit_key() -> str:
    """Scope degradation to the current software-account owner when present."""

    try:
        from app.application.etl.llm_session_provider import current_etl_llm_owner

        owner_user_id = current_etl_llm_owner()
    except Exception:  # noqa: BLE001 - assist scoping must not block preview
        owner_user_id = None
    return f"owner:{owner_user_id}" if owner_user_id is not None else "process"


def _circuit_cooldown_seconds(degradation_code: str) -> float:
    """Use a longer owner cooldown for a confirmed quota exhaustion."""

    env_name = (
        "FHD_ETL_LLM_QUOTA_COOLDOWN_SECONDS"
        if degradation_code == "ETL_LLM_QUOTA_EXHAUSTED"
        else "FHD_ETL_LLM_FAILURE_COOLDOWN_SECONDS"
    )
    default = 300.0 if degradation_code == "ETL_LLM_QUOTA_EXHAUSTED" else 5.0
    raw = str(os.environ.get(env_name) or default).strip()
    try:
        return min(3600.0, max(1.0, float(raw)))
    except ValueError:
        return default


def _circuit_degradation(key: str) -> str:
    now = time.monotonic()
    with _CIRCUIT_LOCK:
        state = _CIRCUIT_OPEN_UNTIL.get(key)
        if state is None:
            return ""
        expires_at, degradation_code = state
        if expires_at <= now:
            _CIRCUIT_OPEN_UNTIL.pop(key, None)
            return ""
        return degradation_code


def _open_circuit(key: str, degradation_code: str) -> None:
    with _CIRCUIT_LOCK:
        _CIRCUIT_OPEN_UNTIL[key] = (
            time.monotonic() + _circuit_cooldown_seconds(degradation_code),
            degradation_code,
        )


def _owner_call_lock(key: str) -> threading.Lock:
    with _CIRCUIT_LOCK:
        lock = _OWNER_CALL_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _OWNER_CALL_LOCKS[key] = lock
        return lock


def _document_cache_key(evidence: dict[str, Any]) -> str:
    evidence_hash = str(evidence.get("evidence_hash") or "").strip()
    if not evidence_hash:
        evidence_hash = hashlib.sha256(
            json.dumps(
                evidence,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        ).hexdigest()
    return f"{_circuit_key()}|{evidence_hash}"


def _document_flight_lock(key: str) -> threading.Lock:
    now = time.monotonic()
    with _DOCUMENT_CACHE_LOCK:
        for expired_key, (expires_at, _result) in list(_DOCUMENT_CACHE.items()):
            if expires_at <= now:
                _DOCUMENT_CACHE.pop(expired_key, None)
                stale_lock = _DOCUMENT_FLIGHT_LOCKS.get(expired_key)
                if stale_lock is not None and not stale_lock.locked():
                    _DOCUMENT_FLIGHT_LOCKS.pop(expired_key, None)
        lock = _DOCUMENT_FLIGHT_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _DOCUMENT_FLIGHT_LOCKS[key] = lock
        return lock


def _cached_document_result(key: str) -> LlmAssistResult | None:
    with _DOCUMENT_CACHE_LOCK:
        cached = _DOCUMENT_CACHE.get(key)
        if cached is None:
            return None
        expires_at, result = cached
        if expires_at <= time.monotonic():
            _DOCUMENT_CACHE.pop(key, None)
            return None
        reused = copy.deepcopy(result)
    reused.billing = {**reused.billing, "reused": True}
    return reused


def _cache_document_result(key: str, result: LlmAssistResult) -> None:
    with _DOCUMENT_CACHE_LOCK:
        _DOCUMENT_CACHE[key] = (
            time.monotonic() + _DOCUMENT_CACHE_TTL_SECONDS,
            copy.deepcopy(result),
        )


def clear_etl_llm_circuit(*, owner_user_id: int | None = None) -> None:
    """Clear transient assist degradation state (primarily for lifecycle/tests).

    This contains only process-local timing/error codes.  It never clears an
    ETL run, a template, an upload, or any account credential.
    """

    with _CIRCUIT_LOCK:
        if owner_user_id is None:
            _CIRCUIT_OPEN_UNTIL.clear()
        else:
            _CIRCUIT_OPEN_UNTIL.pop(f"owner:{int(owner_user_id)}", None)
    cache_prefix = None if owner_user_id is None else f"owner:{int(owner_user_id)}|"
    with _DOCUMENT_CACHE_LOCK:
        if cache_prefix is None:
            _DOCUMENT_CACHE.clear()
            for key, lock in list(_DOCUMENT_FLIGHT_LOCKS.items()):
                if not lock.locked():
                    _DOCUMENT_FLIGHT_LOCKS.pop(key, None)
        else:
            for key in list(_DOCUMENT_CACHE):
                if key.startswith(cache_prefix):
                    _DOCUMENT_CACHE.pop(key, None)
            for key, lock in list(_DOCUMENT_FLIGHT_LOCKS.items()):
                if key.startswith(cache_prefix) and not lock.locked():
                    _DOCUMENT_FLIGHT_LOCKS.pop(key, None)


sync_module_functions(
    target=globals(),
    source_module="app.application.etl.llm_assist",
    function_names=(
        "etl_llm_mode",
        "etl_llm_timeout_seconds",
        "etl_document_timeout_seconds",
        "etl_row_advice_limit",
        "_degradation_code",
        "_circuit_key",
        "_circuit_cooldown_seconds",
        "_circuit_degradation",
        "_open_circuit",
        "_owner_call_lock",
        "_document_cache_key",
        "_document_flight_lock",
        "_cached_document_result",
        "_cache_document_result",
        "clear_etl_llm_circuit",
    ),
)
