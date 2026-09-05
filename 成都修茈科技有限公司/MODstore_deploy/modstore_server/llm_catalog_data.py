"""Fallback loading and record normalization for the LLM catalog."""

from __future__ import annotations

import hashlib
import json
import secrets
from pathlib import Path
from typing import Any, Dict, List, Optional

from modstore_server.operational_errors import RECOVERABLE_ERRORS

_CACHE_KEY_SALT = secrets.token_bytes(32)


def fallback_path() -> Path:
    return Path(__file__).resolve().parent / "data" / "llm_fallback_models.json"


def load_fallback() -> Dict[str, List[Any]]:
    path = fallback_path()
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return {key: list(value) for key, value in raw.items() if isinstance(value, list)}
    except RECOVERABLE_ERRORS:
        return {}


def cache_key(user_id: int, provider: str, api_key: str) -> str:
    payload = f"{user_id}:{provider}:{api_key}".encode("utf-8")
    # A process-random, memory-hard KDF prevents an exposed cache key from
    # becoming an offline oracle for provider credentials. The short result is
    # only an in-process cache identifier, never an authentication verifier.
    digest = hashlib.scrypt(payload, salt=_CACHE_KEY_SALT, n=2**14, r=8, p=1, dklen=16).hex()
    return f"{provider}:{digest}"


def filter_openai_style(ids: List[str]) -> List[str]:
    return sorted(
        {
            model_id
            for item in ids
            if (model_id := str(item or "").strip()) and not model_id.startswith("ft:")
        }
    )


def openai_style_items(data: Any) -> Optional[List[Dict[str, Any]]]:
    if isinstance(data, list):
        return [dict(item) for item in data if isinstance(item, dict)]
    if isinstance(data, dict) and isinstance(data.get("data"), list):
        return [dict(item) for item in data["data"] if isinstance(item, dict)]
    return None


def model_id(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("id", "name", "model"):
            text = str(value.get(key) or "").strip()
            if text:
                return text
        return ""
    return str(value or "").strip()


def merge_model_records(remote: List[str], fallback: List[Any]) -> List[str]:
    models: List[str] = []
    seen: set[str] = set()
    for item in list(remote or []) + list(fallback or []):
        identifier = model_id(item)
        if not identifier or identifier in seen:
            continue
        seen.add(identifier)
        models.append(identifier)
    return sorted(models)


def metadata_by_model_records(
    fallback: List[Any], remote_records: List[Dict[str, Any]]
) -> Dict[str, Dict[str, Any]]:
    metadata: Dict[str, Dict[str, Any]] = {}
    for item in fallback:
        identifier = model_id(item)
        if not identifier:
            continue
        record = dict(item) if isinstance(item, dict) else {"id": identifier}
        record["id"] = identifier
        record["_catalog_origin"] = "fallback"
        metadata[identifier] = record
    for item in remote_records:
        identifier = model_id(item)
        if not identifier:
            continue
        record = dict(item)
        record["id"] = identifier
        record["_catalog_origin"] = "provider_api"
        metadata[identifier] = record
    return metadata


def runtime_model_ids(models_detailed: List[Dict[str, Any]]) -> List[str]:
    return [
        str(row.get("id") or "").strip()
        for row in models_detailed
        if isinstance(row, dict)
        and row.get("runtime_selectable") is True
        and str(row.get("id") or "").strip()
    ]
