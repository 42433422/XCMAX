# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.llm_runtime_autopilot")


def _now_iso() -> str:
    return _facade().datetime.now(_facade().UTC).replace(microsecond=0).isoformat()


def _env_bool(name: str, default: bool) -> bool:
    raw = _facade().os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(_facade().os.environ.get(name, str(default)))
    except ValueError:
        return default


def autopilot_enabled() -> bool:
    return _facade()._env_bool("MODSTORE_LLM_AUTOPILOT_ENABLED", False)


def _failure_threshold() -> int:
    return max(1, _facade()._env_int("MODSTORE_LLM_AUTOPILOT_FAILURE_THRESHOLD", 3))


def _minimum_residence_seconds() -> int:
    return max(0, _facade()._env_int("MODSTORE_LLM_AUTOPILOT_MIN_RESIDENCE_SECONDS", 900))


def _max_candidate_probes() -> int:
    return max(1, min(_facade()._env_int("MODSTORE_LLM_AUTOPILOT_MAX_CANDIDATE_PROBES", 4), 20))


def autopilot_ledger_path() -> _facade().Path:
    root = (
        _facade().os.environ.get("MODSTORE_RUNTIME_DIR")
        or _facade().os.environ.get("MODSTORE_DATA_DIR")
        or "/tmp/modstore_data"
    )
    return _facade().Path(root).expanduser().resolve() / "llm" / "route_autopilot.jsonl"


def _secret_safe(value: _facade().Any) -> _facade().Any:
    from modstore_server.llm_quota_monitor import scrub_llm_error

    if isinstance(value, dict):
        return {str(key): _secret_safe(item) for (key, item) in value.items()}
    if isinstance(value, list):
        return [_secret_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_secret_safe(item) for item in value]
    if isinstance(value, str):
        return scrub_llm_error(value)
    return value


def _read_audit_events() -> list[dict[str, _facade().Any]]:
    path = _facade().autopilot_ledger_path()
    if not path.is_file():
        return []
    try:
        rows = [
            _facade().json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except (OSError, _facade().json.JSONDecodeError):
        return []
    return [row for row in rows if isinstance(row, dict)][-_facade()._MAX_LEDGER_LINES :]


def _write_audit(event: dict[str, _facade().Any]) -> None:
    event = _facade()._secret_safe(event)
    path = _facade().autopilot_ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with _facade()._LOCK:
        lines: list[str] = []
        if path.is_file():
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except OSError:
                lines = []
        lines.append(_facade().json.dumps(event, ensure_ascii=False, sort_keys=True))
        lines = lines[-_facade()._MAX_LEDGER_LINES :]
        tmp = path.with_name(f".{path.name}.{_facade().os.getpid()}.tmp")
        tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
        _facade().os.replace(tmp, path)


def _record(event: dict[str, _facade().Any]) -> dict[str, _facade().Any]:
    safe_event = _facade()._secret_safe(event)
    _facade()._write_audit(safe_event)
    return safe_event


def _consecutive_route_errors(provider: str, model: str) -> int:
    count = 0
    for row in reversed(_facade()._read_audit_events()):
        current = row.get("current") if isinstance(row.get("current"), dict) else {}
        health = row.get("current_health") if isinstance(row.get("current_health"), dict) else {}
        if (
            str(current.get("provider") or "") != provider
            or str(current.get("model") or "") != model
            or str(health.get("state") or "") != "error"
        ):
            break
        count += 1
    return count


def _route_residence_seconds(current: dict[str, _facade().Any] | None) -> float | None:
    if not isinstance(current, dict):
        return None
    raw = str(current.get("switched_at") or "").strip()
    if not raw:
        return None
    try:
        switched_at = _facade().datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if switched_at.tzinfo is None:
            switched_at = switched_at.replace(tzinfo=_facade().UTC)
        return max(0.0, (_facade().datetime.now(_facade().UTC) - switched_at).total_seconds())
    except ValueError:
        return None


def autopilot_status() -> dict[str, _facade().Any]:
    path = _facade().autopilot_ledger_path()
    if not path.is_file():
        return {
            "ok": True,
            "enabled": _facade().autopilot_enabled(),
            "last_run": None,
            "ledger_path": str(path),
            "policy": {
                "failure_threshold": _facade()._failure_threshold(),
                "minimum_residence_seconds": _facade()._minimum_residence_seconds(),
                "max_candidate_probes": _facade()._max_candidate_probes(),
            },
        }
    try:
        lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line]
        last = _facade()._secret_safe(_facade().json.loads(lines[-1])) if lines else None
    except (OSError, _facade().json.JSONDecodeError):
        last = None
    return {
        "ok": True,
        "enabled": _facade().autopilot_enabled(),
        "last_run": last,
        "ledger_path": str(path),
        "policy": {
            "failure_threshold": _facade()._failure_threshold(),
            "minimum_residence_seconds": _facade()._minimum_residence_seconds(),
            "max_candidate_probes": _facade()._max_candidate_probes(),
        },
    }


def _provider_order() -> list[str]:
    raw = _facade().os.environ.get(
        "MODSTORE_LLM_AUTOPILOT_PROVIDER_ORDER",
        "minimax,xiaomi,deepseek,openai,anthropic,google,siliconflow,dashscope,moonshot,openrouter,groq,together",
    )
    return [part.strip().lower() for part in raw.split(",") if part.strip()]


def _ordered_models(provider: str, models: list[str]) -> list[str]:
    from modstore_server.services.llm import _BENCH_DEFAULT_MODELS

    preferred = str(_BENCH_DEFAULT_MODELS.get(provider) or "")
    unique = list(dict.fromkeys((str(model) for model in models if str(model))))
    if preferred in unique:
        return [preferred, *[model for model in unique if model != preferred]]
    return unique


def _quota_by_provider(
    snapshot: dict[str, _facade().Any],
) -> dict[str, dict[str, _facade().Any]]:
    return {
        str(row.get("provider") or ""): row
        for row in snapshot.get("providers") or []
        if isinstance(row, dict) and str(row.get("provider") or "")
    }
