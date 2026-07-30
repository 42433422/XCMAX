import logging
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from typing import BinaryIO

from app.utils.operational_errors import RECOVERABLE_ERRORS

try:
    import pythoncom
    import win32api
    import win32print

    _PRINT_BACKEND_AVAILABLE = True
    _PRINT_BACKEND_ERROR = ""
except ImportError as _print_import_error:
    pythoncom = None
    win32api = None
    win32print = None
    _PRINT_BACKEND_AVAILABLE = False
    _PRINT_BACKEND_ERROR = str(_print_import_error)

logging.basicConfig(level=logging.INFO, encoding="utf-8")
logger = logging.getLogger(__name__)
_CUPS_ERRORS = RECOVERABLE_ERRORS + (subprocess.SubprocessError,)
_CUPS_LP = "/usr/bin/lp"
_CUPS_LPSTAT = "/usr/bin/lpstat"
_CUPS_LPOPTIONS = "/usr/bin/lpoptions"
_CUPS_IPPTOOL = "/usr/bin/ipptool"
_CUPS_PRINTER_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,126}$")
_CUPS_JOB_ID_RE = re.compile(r"\b([A-Za-z0-9][A-Za-z0-9_.-]{0,126}-\d+)\b")
_CUPS_JOB_STATE_RE = re.compile(r"job-state\s+\(enum\)\s+=\s+([^\s]+)", re.IGNORECASE)
_CUPS_JOB_REASONS_RE = re.compile(
    r"job-state-reasons\s+\([^)]*keyword[^)]*\)\s+=\s+(.+)", re.IGNORECASE
)
_CUPS_STATUS_CODE_RE = re.compile(r"status-code\s+=\s+([^\s]+)", re.IGNORECASE)
_CUPS_MONITOR_TIMEOUT_SECONDS = 12.0
_CUPS_MONITOR_INTERVAL_SECONDS = 1.0
_MAC_OSASCRIPT = "/usr/bin/osascript"
_MAC_NUMBERS = "/Applications/Numbers.app"
_NUMBERS_PDF_EXPORT_SCRIPT = """
on run argv
    set sourceFile to POSIX file (item 1 of argv)
    set outputFile to POSIX file (item 2 of argv)
    tell application "Numbers" to launch
    delay 1
    tell application "Numbers"
        set sourceDocument to open sourceFile
        export sourceDocument to outputFile as PDF
        close sourceDocument saving no
    end tell
end run
"""

from app.utils.mixin_module_sync import sync_mixin_methods


class PrintCupsStatusMixin:
    @staticmethod
    def _is_print_backend_available() -> bool:
        return _PRINT_BACKEND_AVAILABLE or PrintCupsStatusMixin._is_cups_backend_available()

    @staticmethod
    def _is_cups_backend_available() -> bool:
        return (
            sys.platform == "darwin"
            and win32print is None
            and win32api is None
            and os.path.isfile(_CUPS_LPSTAT)
            and os.access(_CUPS_LPSTAT, os.X_OK)
            and os.path.isfile(_CUPS_LP)
            and os.access(_CUPS_LP, os.X_OK)
        )

    def _build_unavailable_result(self) -> dict:
        if sys.platform == "darwin":
            detail = "未找到 macOS CUPS 命令 lpstat/lp"
        else:
            detail = f"缺少 Windows 打印依赖：{_PRINT_BACKEND_ERROR or 'unknown'}"
        message = f"当前环境不支持打印功能（{detail}）"
        return {"success": False, "message": message}

    @staticmethod
    def _cups_env() -> dict[str, str]:
        return {
            **os.environ,
            "LC_ALL": "C",
            "LANG": "C",
        }

    @classmethod
    def _run_cups(
        cls,
        command: str,
        arguments: tuple[str, ...],
        *,
        timeout: float = 15,
        input_stream: BinaryIO | None = None,
    ) -> subprocess.CompletedProcess[str]:
        if command == "lp":
            executable = _CUPS_LP
        elif command == "lpstat":
            executable = _CUPS_LPSTAT
        elif command == "lpoptions":
            executable = _CUPS_LPOPTIONS
        else:
            raise ValueError("unsupported CUPS command")
        return subprocess.run(
            [executable, *arguments],
            stdin=input_stream,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env=cls._cups_env(),
        )

    @classmethod
    def _run_ipp_query(
        cls,
        printer_name: str,
        job_number: int,
        *,
        timeout: float = 5,
    ) -> subprocess.CompletedProcess[str]:
        """Read one CUPS job's authoritative IPP state without shelling out."""

        if not os.path.isfile(_CUPS_IPPTOOL) or not os.access(_CUPS_IPPTOOL, os.X_OK):
            raise FileNotFoundError("macOS CUPS ipptool is unavailable")
        if not _CUPS_PRINTER_NAME_RE.fullmatch(printer_name):
            raise ValueError("unsafe CUPS printer name")
        if job_number <= 0:
            raise ValueError("invalid CUPS job number")

        request = "\n".join(
            (
                "{",
                "OPERATION Get-Job-Attributes",
                "GROUP operation-attributes-tag",
                "ATTR charset attributes-charset utf-8",
                "ATTR language attributes-natural-language en",
                "ATTR uri printer-uri $uri",
                f"ATTR integer job-id {job_number}",
                "ATTR keyword requested-attributes job-id,job-state,job-state-reasons",
                "}",
                "",
            )
        )
        uri = f"ipp://localhost/printers/{printer_name}"
        bounded_timeout = max(1.0, float(timeout))
        return subprocess.run(
            # ``-v`` is essential: plain ``-t`` only emits [PASS]/[FAIL],
            # not the returned IPP attributes we need to prove completion.
            [_CUPS_IPPTOOL, "-t", "-v", "-T", str(int(bounded_timeout)), uri, "/dev/stdin"],
            input=request,
            capture_output=True,
            text=True,
            timeout=bounded_timeout + 2.0,
            check=False,
            env=cls._cups_env(),
        )

    @staticmethod
    def _cups_submission_job_id(raw_output: str) -> str | None:
        """Extract the canonical ``printer-N`` id emitted by ``lp``."""

        match = _CUPS_JOB_ID_RE.search(str(raw_output or ""))
        return match.group(1) if match else None

    def _cups_job_ids(self, printer_name: str) -> set[str]:
        """Return all CUPS job ids currently known for one destination."""

        if not _CUPS_PRINTER_NAME_RE.fullmatch(printer_name):
            return set()
        try:
            result = self._run_cups("lpstat", ("-W", "all", "-o", printer_name))
        except _CUPS_ERRORS as exc:
            logger.warning("CUPS job inventory failed for %s: %s", printer_name, exc)
            return set()
        if result.returncode != 0:
            return set()
        prefix = f"{printer_name}-"
        return {
            match.group(1)
            for match in _CUPS_JOB_ID_RE.finditer(str(result.stdout or ""))
            if match.group(1).startswith(prefix)
        }

    def _detect_submitted_cups_job_id(
        self,
        printer_name: str,
        *,
        before: set[str],
        timeout: float = 2.0,
        interval: float = 0.1,
    ) -> str | None:
        """Recover an omitted ``lp`` id only when one new job is unambiguous."""
        deadline = time.monotonic() + max(0.0, float(timeout))
        while time.monotonic() < deadline:
            candidates = self._cups_job_ids(printer_name) - set(before)
            if len(candidates) == 1:
                return next(iter(candidates))
            if len(candidates) > 1:
                return None
            threading.Event().wait(
                min(max(0.05, float(interval)), max(0.0, deadline - time.monotonic()))
            )
        return None

    @staticmethod
    def _cups_job_number(printer_name: str, job_id: str) -> int | None:
        """Validate that a CUPS job belongs to the selected destination."""

        prefix, separator, raw_number = str(job_id or "").rpartition("-")
        if (
            not separator
            or prefix != printer_name
            or not raw_number.isdigit()
            or not _CUPS_PRINTER_NAME_RE.fullmatch(printer_name)
        ):
            return None
        number = int(raw_number)
        return number if number > 0 else None

    @staticmethod
    def _normalize_cups_job_state(raw_state: str) -> str:
        state = str(raw_state or "").strip().lower()
        state_map = {
            "3": "pending",
            "4": "pending",
            "5": "pending",
            "6": "pending",
            "7": "aborted",
            "8": "aborted",
            "9": "completed",
            "pending": "pending",
            "pending-held": "pending",
            "processing": "pending",
            "processing-stopped": "pending",
            "canceled": "aborted",
            "cancelled": "aborted",
            "aborted": "aborted",
            "completed": "completed",
        }
        return state_map.get(state, "unknown")

    def _get_cups_job_state(self, printer_name: str, job_id: str) -> dict:
        """Return completed, aborted, pending, or unknown without false receipts."""

        job_number = self._cups_job_number(printer_name, job_id)
        if job_number is None:
            return {
                "state": "unknown",
                "job_id": job_id,
                "reason": "invalid CUPS job identifier",
                "query_available": False,
            }
        try:
            result = self._run_ipp_query(printer_name, job_number)
        except _CUPS_ERRORS as exc:
            logger.warning("CUPS job-state query failed for %s: %s", job_id, exc)
            return {
                "state": "unknown",
                "job_id": job_id,
                "reason": "CUPS job-state query unavailable",
                "query_available": False,
            }

        output = "\n".join((str(result.stdout or ""), str(result.stderr or "")))
        status_match = _CUPS_STATUS_CODE_RE.search(output)
        status_code = status_match.group(1).lower() if status_match else ""
        if result.returncode != 0 or (status_code and not status_code.startswith("successful")):
            return {
                "state": "unknown",
                "job_id": job_id,
                "reason": "CUPS did not return a usable job state",
                "query_available": True,
            }

        state_match = _CUPS_JOB_STATE_RE.search(output)
        normalized_state = self._normalize_cups_job_state(
            state_match.group(1) if state_match else ""
        )
        reasons_match = _CUPS_JOB_REASONS_RE.search(output)
        return {
            "state": normalized_state,
            "job_id": job_id,
            "reason": reasons_match.group(1).strip() if reasons_match else "",
            "query_available": True,
        }

    def _monitor_cups_job(
        self,
        printer_name: str,
        job_id: str,
        *,
        timeout: float = _CUPS_MONITOR_TIMEOUT_SECONDS,
        interval: float = _CUPS_MONITOR_INTERVAL_SECONDS,
    ) -> dict:
        """Bounded state monitor for a just-submitted CUPS print job."""
        deadline = time.monotonic() + max(0.0, float(timeout))
        last: dict = {"state": "unknown", "job_id": job_id, "query_available": False}
        while time.monotonic() < deadline:
            last = self._get_cups_job_state(printer_name, job_id)
            state = str(last.get("state") or "unknown")
            if state in {"completed", "aborted"}:
                return last
            if state == "unknown" and not last.get("query_available"):
                return {**last, "state": "pending", "timed_out": False}
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return {**last, "state": "pending", "timed_out": True}
            threading.Event().wait(min(max(0.05, float(interval)), remaining))
        return {**last, "state": "pending", "timed_out": True}

    def get_cups_print_job_status(self, printer_name: str, job_id: str) -> dict:
        """Read the current state of a previously submitted CUPS job.

        This intentionally performs no submission, cancellation, or printer
        configuration change.  It is used by the owner-bound pending-job
        endpoint after the initial bounded monitor has returned ``pending``.
        """

        normalized_printer = str(printer_name or "").strip()
        normalized_job = str(job_id or "").strip()
        if not _CUPS_PRINTER_NAME_RE.fullmatch(normalized_printer):
            return {
                "state": "unknown",
                "job_id": normalized_job,
                "reason": "invalid CUPS printer",
                "query_available": False,
            }
        return self._get_cups_job_state(normalized_printer, normalized_job)

    def _get_cups_default_printer(self) -> str | None:
        try:
            result = self._run_cups("lpstat", ("-d",))
            if result.returncode != 0:
                return None
            line = result.stdout.strip()
            for prefix in (
                "system default destination:",
                "系统默认目的位置：",
                "系统默认目的位置:",
            ):
                if line.lower().startswith(prefix.lower()):
                    return line[len(prefix) :].strip() or None
        except _CUPS_ERRORS as exc:
            logger.warning("CUPS default printer query failed: %s", exc)
        return None

    @staticmethod
    def _cups_status_text(raw: str, state_reasons: list[str] | None = None) -> str:
        reasons = [str(reason or "").strip().lower() for reason in (state_reasons or [])]
        reasons = [reason for reason in reasons if reason and reason != "none"]
        if reasons:
            if any("media-empty" in reason or "media-needed" in reason for reason in reasons):
                return "缺纸"
            if any("paused" in reason for reason in reasons):
                return "已暂停"
            if any("offline" in reason for reason in reasons):
                return "离线"
            return "异常"
        normalized = raw.lower()
        if "disabled" in normalized or "paused" in normalized or "已停用" in raw or "暂停" in raw:
            return "已暂停"
        if (
            "printing" in normalized
            or "processing" in normalized
            or "正在打印" in raw
            or "正在处理" in raw
        ):
            return "打印中"
        if "idle" in normalized or "enabled" in normalized or "闲置" in raw:
            return "就绪"
        return "未知"

    def _get_cups_printer_state_reasons(self, printer_name: str) -> list[str]:
        """Return normalized CUPS state reasons for a destination.

        ``lpstat -p`` may say ``idle`` even when the IPP destination has an
        ``offline-report`` or ``media-empty-error`` reason.  Do not advertise a
        printer as ready in that state: a delivery document would otherwise be
        marked printed solely because CUPS accepted a queue entry.
        """

        if not _CUPS_PRINTER_NAME_RE.fullmatch(printer_name):
            return []
        if not os.path.isfile(_CUPS_LPOPTIONS) or not os.access(_CUPS_LPOPTIONS, os.X_OK):
            return []
        try:
            result = self._run_cups("lpoptions", ("-p", printer_name))
        except _CUPS_ERRORS as exc:
            logger.warning("CUPS printer-state reason query failed for %s: %s", printer_name, exc)
            return []
        if result.returncode != 0:
            return []
        match = re.search(r"(?:^|\s)printer-state-reasons=([^\s]+)", result.stdout or "")
        if not match:
            return []
        reasons = [part.strip().lower() for part in match.group(1).split(",")]
        return [reason for reason in reasons if reason and reason != "none"]

    @classmethod
    def _parse_cups_printer_line(cls, line: str) -> tuple[str, str] | None:
        if line.startswith("printer "):
            parts = line.split(maxsplit=2)
            if len(parts) >= 2:
                return parts[1], cls._cups_status_text(parts[2] if len(parts) == 3 else "")
            return None
        if line.startswith("打印机"):
            body = line[len("打印机") :]
            markers = ("正在打印", "正在处理", "已停用", "暂停", "闲置")
            positions = [(body.find(marker), marker) for marker in markers if body.find(marker) > 0]
            if positions:
                index, marker = min(positions, key=lambda item: item[0])
                return body[:index].strip(), cls._cups_status_text(marker)
        return None

    def _get_cups_printers(self) -> list[dict[str, object]]:
        try:
            result = self._run_cups("lpstat", ("-p",))
            if result.returncode != 0:
                logger.warning("CUPS printer query failed: %s", result.stderr.strip())
                return []
            default_printer = self._get_cups_default_printer()
            printers: list[dict[str, object]] = []
            for raw_line in result.stdout.splitlines():
                line = raw_line.strip()
                parsed = self._parse_cups_printer_line(line)
                if parsed is None:
                    continue
                name, status = parsed
                state_reasons = self._get_cups_printer_state_reasons(name)
                # ``_parse_cups_printer_line`` already normalises the
                # lpstat text (for example idle -> 就绪).  Apply IPP reasons
                # as an override, not as a second raw-status parse.
                resolved_status = (
                    self._cups_status_text(status, state_reasons) if state_reasons else status
                )
                printer = {
                    "name": name,
                    "status": resolved_status,
                    "is_default": name == default_printer,
                }
                if state_reasons:
                    printer["state_reasons"] = state_reasons
                    printer["is_printable"] = False
                else:
                    # A CUPS destination can safely accept another job while
                    # it is printing; only explicit IPP reasons or an unknown
                    # / paused state make it non-printable.
                    printer["is_printable"] = printer["status"] in {"就绪", "打印中"}
                printers.append(printer)
            return printers
        except _CUPS_ERRORS as exc:
            logger.error("CUPS printer discovery failed: %s", exc)
            return []

    def _resolve_cups_printer_name(self, requested: str) -> str | None:
        if not _CUPS_PRINTER_NAME_RE.fullmatch(requested):
            return None
        for printer in self._get_cups_printers():
            candidate = str(printer.get("name") or "")
            if candidate == requested and _CUPS_PRINTER_NAME_RE.fullmatch(candidate):
                return candidate
        return None


sync_mixin_methods(
    PrintCupsStatusMixin,
    target=globals(),
    source_module="app.utils.print_utils",
    method_names=(
        "_is_print_backend_available",
        "_is_cups_backend_available",
        "_build_unavailable_result",
        "_cups_env",
        "_run_cups",
        "_run_ipp_query",
        "_cups_submission_job_id",
        "_cups_job_ids",
        "_detect_submitted_cups_job_id",
        "_cups_job_number",
        "_normalize_cups_job_state",
        "_get_cups_job_state",
        "_monitor_cups_job",
        "get_cups_print_job_status",
        "_get_cups_default_printer",
        "_cups_status_text",
        "_get_cups_printer_state_reasons",
        "_parse_cups_printer_line",
        "_get_cups_printers",
        "_resolve_cups_printer_name",
    ),
)
