"""凭据统一托管（第一版）：统一读取、任务短期授权、访问审计与脱敏。

- ``get_credential(name, task_id, purpose)``：按后端顺序读取凭据，每次访问写一条审计
  （谁、何时、哪个任务、什么用途、哪个后端、结果），审计里永远不写凭据值。
- 后端可插拔：已实现 ``env``、``file``（目录内一个凭据一个文件，权限须不宽于 0600）；
  ``vault`` / ``kms`` 只预留接口，选用时明确报未实现，不静默回退。
- 短期授权：派单时为任务签发带作用域和过期时间的授权引用，任务结束或过期即失效；
  引用里只有授权编号、任务、作用域和过期时间，不含任何凭据值。
- 脱敏：``redact`` 替换已读取过的凭据值、环境变量里的密钥值和常见令牌形态；
  ``install_log_redaction`` 让本进程所有日志在生成时先脱敏。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import threading
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import (
    Any,
    Dict,
    Iterable,
    List,
    Mapping,
    Optional,
    Protocol,
    Sequence,
    Tuple,
)

logger = logging.getLogger(__name__)

GRANT_PROMPT_KEY = "MODSTORE_CREDENTIAL_GRANT"
SIGNING_KEY_NAME = "MODSTORE_CREDENTIAL_GRANT_SIGNING_KEY"
_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,127}$")
_SECRET_NAME_RE = re.compile(
    r"(PASSWORD|PASSWD|SECRET|TOKEN|API_KEY|APIKEY|PRIVATE_KEY|CREDENTIAL)"
)
_NON_SECRET_VALUES = {
    "",
    "0",
    "1",
    "true",
    "false",
    "yes",
    "no",
    "on",
    "off",
    "none",
    "null",
}
_KEY_VALUE_RE = re.compile(
    r"(?i)(bearer\s+|(?:api[_-]?key|password|passwd|token|secret|authorization)\s*[:=]\s*(?:bearer\s+)?)"
    r"[^\s,;'\"]+"
)
_TOKEN_SHAPES_RE = re.compile(
    r"(sk-[A-Za-z0-9_\-]{12,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}"
    r"|AKID[A-Za-z0-9]{12,}|eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]+)"
)
REDACTED = "[REDACTED]"


class CredentialError(RuntimeError):
    """凭据不可用、授权失效或后端不可用；消息里不含凭据值。"""


class CredentialBackend(Protocol):
    name: str

    def fetch(self, credential_name: str) -> Optional[str]: ...


class EnvBackend:
    name = "env"

    def __init__(self, environ: Optional[Mapping[str, str]] = None) -> None:
        self._environ = environ

    def fetch(self, credential_name: str) -> Optional[str]:
        env = os.environ if self._environ is None else self._environ
        value = str(env.get(credential_name) or "").strip()
        return value or None


class FileBackend:
    """目录内每个凭据一个文件（文件名即凭据名）。权限宽于 0600 时拒读。"""

    name = "file"

    def __init__(self, directory: str | Path) -> None:
        self._directory = Path(directory).expanduser()

    def fetch(self, credential_name: str) -> Optional[str]:
        path = self._directory / credential_name
        if not path.is_file():
            return None
        if os.name == "posix" and path.stat().st_mode & 0o077:
            raise CredentialError(f"凭据文件权限过宽（须 0600）：{credential_name}")
        value = path.read_text(encoding="utf-8").strip()
        return value or None


class ReservedBackend:
    """Vault / 云 KMS 预留接口：选用即报未实现，不静默回退到其他后端。"""

    def __init__(self, name: str) -> None:
        self.name = name

    def fetch(self, credential_name: str) -> Optional[str]:
        raise CredentialError(f"凭据后端 {self.name} 尚未实现（预留接口）")


def default_backends(
    environ: Optional[Mapping[str, str]] = None,
) -> List[CredentialBackend]:
    env = os.environ if environ is None else environ
    file_dir = str(env.get("MODSTORE_CREDENTIAL_FILE_DIR") or "").strip()
    order = str(env.get("MODSTORE_CREDENTIAL_BACKENDS") or "").strip()
    names = [n.strip().lower() for n in order.split(",") if n.strip()] or (
        ["file", "env"] if file_dir else ["env"]
    )
    out: List[CredentialBackend] = []
    for name in names:
        if name == "env":
            out.append(EnvBackend(environ))
        elif name == "file":
            if not file_dir:
                raise CredentialError("选用 file 后端但未配置 MODSTORE_CREDENTIAL_FILE_DIR")
            out.append(FileBackend(file_dir))
        elif name in {"vault", "kms"}:
            out.append(ReservedBackend(name))
        else:
            raise CredentialError(f"未知凭据后端：{name}")
    return out


def _audit_dir() -> Path:
    raw = (
        os.environ.get("MODSTORE_CREDENTIAL_AUDIT_DIR")
        or os.environ.get("MODSTORE_RUNTIME_DIR")
        or "/tmp/modstore_runtime"
    )
    path = Path(raw).expanduser()
    if path.name != "credential_audit":
        path = path / "credential_audit"
    return path


_LOCK = threading.Lock()
_KNOWN_VALUES: set[str] = set()
_REVOKED_TASKS: Dict[str, float] = {}
_PROCESS_KEY = secrets.token_bytes(32)
_AUDIT_ROTATE_BYTES = 20 * 1024 * 1024


def audit_log_path() -> Path:
    return _audit_dir() / "credential_access.jsonl"


def _revocation_path() -> Path:
    return _audit_dir() / "revoked_tasks.json"


def write_audit(event: str, **fields: Any) -> Dict[str, Any]:
    """写一条审计记录。调用方禁止传入凭据值；字段名含 value 的一律丢弃。"""

    record: Dict[str, Any] = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "event": event,
        "pid": os.getpid(),
    }
    for key, value in fields.items():
        if "value" in key.lower() or value is None:
            continue
        record[key] = value if isinstance(value, (int, float, bool, list)) else str(value)[:300]
    try:
        path = audit_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_file() and path.stat().st_size > _AUDIT_ROTATE_BYTES:
            path.replace(path.with_name(path.name + ".1"))
        with _LOCK, path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    except OSError:
        logger.warning("credential audit write failed: event=%s", event)
    return record


def _remember(value: str) -> None:
    if len(value) >= 6:
        with _LOCK:
            _KNOWN_VALUES.add(value)


def get_credential(
    name: str,
    task_id: str,
    purpose: str,
    *,
    actor: str = "modstore",
    aliases: Sequence[str] = (),
    required: bool = False,
    grant: Optional["TaskGrant"] = None,
    backends: Optional[Sequence[CredentialBackend]] = None,
) -> Optional[str]:
    """读取凭据并审计。``task_id`` 与 ``purpose`` 必填；带 ``grant`` 时先校验作用域与时效。"""

    if not _NAME_RE.match(name or ""):
        raise ValueError("凭据名须为大写下划线变量名")
    if not str(task_id or "").strip() or not str(purpose or "").strip():
        raise ValueError("get_credential 需要 task_id 与 purpose 用于审计")
    base = {"credential": name, "task_id": task_id, "purpose": purpose, "actor": actor}
    if grant is not None:
        reason = grant.denial_reason(name)
        if reason:
            write_audit(
                "access",
                outcome="denied",
                reason=reason,
                grant_id=grant.grant_id,
                **base,
            )
            raise CredentialError(f"任务授权不允许读取 {name}：{reason}")
    for candidate in (name, *aliases):
        for backend in backends if backends is not None else default_backends():
            value = backend.fetch(candidate)
            if value:
                _remember(value)
                write_audit(
                    "access",
                    outcome="hit",
                    backend=backend.name,
                    resolved=candidate,
                    grant_id=grant.grant_id if grant else None,
                    **base,
                )
                return value
    write_audit("access", outcome="miss", **base)
    if required:
        raise CredentialError(f"凭据 {name} 未配置")
    return None


@dataclass(frozen=True)
class TaskGrant:
    grant_id: str
    task_id: str
    scopes: Tuple[str, ...]
    issued_at: int
    expires_at: int
    signature: str

    def payload(self) -> Dict[str, Any]:
        return {
            "grant_id": self.grant_id,
            "task_id": self.task_id,
            "scopes": list(self.scopes),
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
        }

    def denial_reason(self, name: str = "", now: Optional[float] = None) -> str:
        if (time.time() if now is None else now) >= self.expires_at:
            return "expired"
        if is_task_revoked(self.task_id):
            return "revoked"
        if name and name not in self.scopes:
            return "out_of_scope"
        return ""

    def prompt_line(self) -> str:
        """写进派单提示词的授权引用：只有编号、任务、作用域、过期时间，没有凭据值。"""

        return GRANT_PROMPT_KEY + "=" + json.dumps(self.payload(), separators=(",", ":"))

    def token(self) -> str:
        body = json.dumps(self.payload(), separators=(",", ":"), sort_keys=True).encode()
        return base64.urlsafe_b64encode(body).decode().rstrip("=") + "." + self.signature


def _signing_key() -> bytes:
    key = EnvBackend().fetch(SIGNING_KEY_NAME)
    return key.encode("utf-8") if key else _PROCESS_KEY


def _sign(payload: Mapping[str, Any]) -> str:
    body = json.dumps(dict(payload), separators=(",", ":"), sort_keys=True).encode()
    return hmac.new(_signing_key(), body, hashlib.sha256).hexdigest()


def _ttl(ttl_seconds: Optional[int]) -> int:
    raw = ttl_seconds or int(os.environ.get("MODSTORE_CREDENTIAL_GRANT_TTL_SECONDS") or 3600)
    return max(60, min(int(raw), 86400))


def default_grant_scopes() -> Tuple[str, ...]:
    raw = os.environ.get("MODSTORE_CREDENTIAL_GRANT_SCOPES", "OPENAI_API_KEY,CODEX_API_KEY")
    return tuple(s.strip() for s in raw.split(",") if _NAME_RE.match(s.strip()))


def issue_task_grant(
    task_id: str,
    scopes: Iterable[str],
    *,
    purpose: str,
    ttl_seconds: Optional[int] = None,
    actor: str = "modstore",
) -> TaskGrant:
    task = str(task_id or "").strip()
    if not task:
        raise ValueError("签发任务授权需要 task_id")
    clean = tuple(sorted({s for s in scopes if _NAME_RE.match(s)}))
    now = int(time.time())
    unsigned = TaskGrant(
        grant_id="cg_" + secrets.token_hex(8),
        task_id=task,
        scopes=clean,
        issued_at=now,
        expires_at=now + _ttl(ttl_seconds),
        signature="",
    )
    grant = replace(unsigned, signature=_sign(unsigned.payload()))
    write_audit(
        "grant_issue",
        grant_id=grant.grant_id,
        task_id=task,
        scopes=list(clean),
        expires_at=grant.expires_at,
        purpose=purpose,
        actor=actor,
    )
    return grant


def verify_grant_token(token: str, now: Optional[float] = None) -> TaskGrant:
    try:
        body_b64, signature = str(token or "").rsplit(".", 1)
        body = base64.urlsafe_b64decode(body_b64 + "=" * (-len(body_b64) % 4))
        payload = json.loads(body)
        grant = TaskGrant(
            grant_id=str(payload["grant_id"]),
            task_id=str(payload["task_id"]),
            scopes=tuple(payload["scopes"]),
            issued_at=int(payload["issued_at"]),
            expires_at=int(payload["expires_at"]),
            signature=signature,
        )
    except (ValueError, KeyError, TypeError) as exc:
        raise CredentialError("任务授权格式无效") from exc
    if not hmac.compare_digest(_sign(grant.payload()), signature):
        raise CredentialError("任务授权签名无效")
    reason = grant.denial_reason(now=now)
    if reason:
        raise CredentialError(f"任务授权已失效：{reason}")
    return grant


def _load_revocations() -> Dict[str, float]:
    try:
        data = json.loads(_revocation_path().read_text(encoding="utf-8"))
        return {str(k): float(v) for k, v in data.items()} if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def revoke_task_grants(task_id: str, reason: str, actor: str = "modstore") -> None:
    task = str(task_id or "").strip()
    if not task:
        return
    with _LOCK:
        _REVOKED_TASKS[task] = time.time()
        merged = {**_load_revocations(), **_REVOKED_TASKS}
        cutoff = time.time() - 7 * 86400
        merged = {k: v for k, v in merged.items() if v >= cutoff}
        try:
            path = _revocation_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(merged, sort_keys=True), encoding="utf-8")
        except OSError:
            logger.warning("credential revocation persist failed: task=%s", task)
    write_audit("grant_revoke", task_id=task, reason=reason, actor=actor)


def is_task_revoked(task_id: str) -> bool:
    task = str(task_id or "").strip()
    return bool(task) and (task in _REVOKED_TASKS or task in _load_revocations())


def _env_secret_values(environ: Optional[Mapping[str, str]] = None) -> List[str]:
    env = os.environ if environ is None else environ
    out = []
    for key, value in env.items():
        val = str(value or "").strip()
        if (
            _SECRET_NAME_RE.search(key.upper())
            and len(val) >= 8
            and val.lower() not in _NON_SECRET_VALUES
        ):
            out.append(val)
    return out


def redact(text: Any, extra_values: Iterable[str] = ()) -> str:
    """把已知凭据值、环境变量里的密钥值和常见令牌形态替换为 [REDACTED]。"""

    out = str(text if text is not None else "")
    if not out:
        return out
    with _LOCK:
        values = set(_KNOWN_VALUES)
    values.update(v for v in extra_values if v and len(v) >= 6)
    values.update(_env_secret_values())
    for value in sorted(values, key=len, reverse=True):
        if value in out:
            out = out.replace(value, REDACTED)
    out = _KEY_VALUE_RE.sub(lambda m: m.group(1) + REDACTED, out)
    return _TOKEN_SHAPES_RE.sub(REDACTED, out)


_FACTORY_MARK = "_modstore_credential_redaction"


def install_log_redaction() -> bool:
    """包装 LogRecord 工厂，让本进程所有日志生成时先脱敏；重复调用无副作用。"""

    current = logging.getLogRecordFactory()
    if getattr(current, _FACTORY_MARK, False):
        return False

    def factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
        record = current(*args, **kwargs)
        try:
            message = record.getMessage()
        except (TypeError, ValueError):
            return record
        cleaned = redact(message)
        if cleaned != message:
            record.msg, record.args = cleaned, ()
        return record

    setattr(factory, _FACTORY_MARK, True)
    logging.setLogRecordFactory(factory)
    return True
