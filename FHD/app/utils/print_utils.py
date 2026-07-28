import logging
import os
import re
import subprocess
import sys
import tempfile
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


class PrinterUtils:
    def __init__(self):
        self._com_initialized = False

    @staticmethod
    def _is_print_backend_available() -> bool:
        return _PRINT_BACKEND_AVAILABLE or PrinterUtils._is_cups_backend_available()

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
        """Read one CUPS job's authoritative IPP state without shelling out.

        ``lp`` only tells us that CUPS accepted a job.  IPP's
        ``Get-Job-Attributes`` is the portable macOS/CUPS way to distinguish a
        queued job from a completed, cancelled, or aborted job before the
        business record is marked printed.
        """

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
        """Return ``completed``, ``aborted``, ``pending``, or ``unknown``.

        A query failure is deliberately not treated as completion.  The caller
        will keep the delivery order in a queued/pending state instead of
        writing a false "printed" receipt.
        """

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
        while True:
            last = self._get_cups_job_state(printer_name, job_id)
            state = str(last.get("state") or "unknown")
            if state in {"completed", "aborted"}:
                return last
            if state == "unknown" and not last.get("query_available"):
                return {**last, "state": "pending", "timed_out": False}
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return {**last, "state": "pending", "timed_out": True}
            time.sleep(min(max(0.05, float(interval)), remaining))

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

    @staticmethod
    def _allowed_print_roots() -> tuple[str, ...]:
        from app.utils.path_utils import get_app_data_dir

        app_data = os.path.realpath(get_app_data_dir())
        roots = {
            app_data,
            os.path.join(app_data, "shipment_outputs"),
            os.path.realpath(tempfile.gettempdir()),
        }
        configured = os.environ.get("XCAGI_PRINT_ALLOWED_ROOTS", "")
        for value in configured.split(os.pathsep):
            value = value.strip()
            if value:
                roots.add(os.path.realpath(value))
        return tuple(sorted(roots))

    @classmethod
    def _resolve_allowed_print_path(cls, file_path: str) -> str | None:
        requested = os.path.realpath(os.path.abspath(file_path))
        for root in cls._allowed_print_roots():
            normalized_root = os.path.realpath(root)
            try:
                with os.scandir(normalized_root) as entries:
                    for entry in entries:
                        if not entry.is_file(follow_symlinks=False):
                            continue
                        candidate = os.path.realpath(entry.path)
                        if os.path.normcase(candidate) == os.path.normcase(requested):
                            return candidate
            except OSError:
                continue
        return None

    def _print_cups(self, file_path: str, printer_name: str) -> dict:
        validated_printer = self._resolve_cups_printer_name(printer_name)
        if validated_printer is None:
            return {
                "success": False,
                "message": "打印失败：打印机不存在或名称不安全",
                "printer": printer_name,
            }
        validated_file = self._resolve_allowed_print_path(file_path)
        if validated_file is None:
            return {
                "success": False,
                "message": "打印失败：文件不在允许的打印目录中",
                "printer": validated_printer,
            }
        try:
            with open(validated_file, "rb") as source:
                result = self._run_cups(
                    "lp",
                    ("-d", validated_printer),
                    timeout=30,
                    input_stream=source,
                )
            if result.returncode != 0:
                logger.warning(
                    "CUPS rejected print job for %s: %s",
                    validated_printer,
                    result.stderr.strip() or result.stdout.strip() or "lp command failed",
                )
                return {
                    "success": False,
                    "message": "打印失败：macOS 打印服务拒绝了任务",
                    "printer": validated_printer,
                }
            job_id = self._cups_submission_job_id(
                "\n".join((str(result.stdout or ""), str(result.stderr or "")))
            )
            if not job_id:
                # CUPS accepted the document but did not return an id we can
                # inspect.  Never turn that into a completed/printed receipt.
                return {
                    "success": True,
                    "message": "打印任务已提交到 macOS CUPS，正在等待设备完成",
                    "file": os.path.basename(validated_file),
                    "printer": validated_printer,
                    "method": "cups_lp",
                    "print_completed": False,
                    "print_state": "queued",
                }

            monitor = self._monitor_cups_job(validated_printer, job_id)
            state = str(monitor.get("state") or "pending")
            if state == "completed":
                return {
                    "success": True,
                    "message": "打印任务已由 macOS CUPS 确认完成",
                    "file": os.path.basename(validated_file),
                    "printer": validated_printer,
                    "method": "cups_lp",
                    "job_id": job_id,
                    "print_completed": True,
                    "print_state": "completed",
                }
            if state == "aborted":
                reason = str(monitor.get("reason") or "").strip()
                return {
                    "success": False,
                    "message": "打印失败：macOS 打印任务已中止" + (f"（{reason}）" if reason else ""),
                    "printer": validated_printer,
                    "method": "cups_lp",
                    "job_id": job_id,
                    "print_completed": False,
                    "print_state": "aborted",
                    "error_code": "CUPS_JOB_ABORTED",
                }
            return {
                "success": True,
                "message": "打印任务已提交到 macOS CUPS，正在等待设备完成",
                "file": os.path.basename(validated_file),
                "printer": validated_printer,
                "method": "cups_lp",
                "job_id": job_id,
                "print_completed": False,
                "print_state": "queued",
            }
        except _CUPS_ERRORS as exc:
            logger.error("CUPS print failed: %s", exc)
            return {
                "success": False,
                "message": "打印失败：macOS 打印服务暂不可用",
                "printer": validated_printer,
            }

    def _convert_excel_to_pdf_macos(self, file_path: str) -> tuple[str | None, str]:
        validated_file = self._resolve_allowed_print_path(file_path)
        if validated_file is None:
            return None, "发货单文件不在允许的打印目录中"
        if not (
            os.path.isfile(_MAC_OSASCRIPT)
            and os.access(_MAC_OSASCRIPT, os.X_OK)
            and os.path.isdir(_MAC_NUMBERS)
        ):
            return None, "未安装 Apple Numbers，无法将 Excel 发货单转换为可打印格式"

        file_descriptor, pdf_path = tempfile.mkstemp(
            prefix="xcagi-shipment-print-",
            suffix=".pdf",
            dir=tempfile.gettempdir(),
        )
        os.close(file_descriptor)
        os.unlink(pdf_path)
        try:
            result = subprocess.run(
                [
                    _MAC_OSASCRIPT,
                    "-e",
                    _NUMBERS_PDF_EXPORT_SCRIPT,
                    validated_file,
                    pdf_path,
                ],
                capture_output=True,
                text=True,
                timeout=90,
                check=False,
            )
            if result.returncode != 0 or not os.path.isfile(pdf_path):
                detail = result.stderr.strip() or result.stdout.strip()
                logger.warning("Numbers PDF export failed: %s", detail or "unknown error")
                if os.path.exists(pdf_path):
                    os.unlink(pdf_path)
                return None, "Numbers 转换发货单失败，请检查自动化权限后重试"
            return pdf_path, ""
        except _CUPS_ERRORS as exc:
            logger.warning("Numbers PDF export unavailable: %s", exc)
            if os.path.exists(pdf_path):
                os.unlink(pdf_path)
            return None, "Numbers 转换发货单失败，请检查自动化权限后重试"

    def _print_excel_macos(self, file_path: str, printer_name: str) -> dict:
        pdf_path, error = self._convert_excel_to_pdf_macos(file_path)
        if pdf_path is None:
            return {
                "success": False,
                "message": f"打印失败：{error}",
                "printer": printer_name,
            }
        try:
            result = self._print_cups(pdf_path, printer_name)
            if result.get("success"):
                result.update(
                    {
                        "file": os.path.basename(file_path),
                        "method": "numbers_pdf_cups",
                    }
                )
            return result
        finally:
            try:
                os.unlink(pdf_path)
            except OSError:
                logger.warning("Unable to remove temporary print PDF: %s", pdf_path)

    def _monitor_cups_print_job(self, printer_name: str, timeout: int) -> bool:
        validated_printer = self._resolve_cups_printer_name(printer_name)
        if validated_printer is None:
            return False
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                result = self._run_cups("lpstat", ("-o", validated_printer))
                if result.returncode == 0 and not result.stdout.strip():
                    return True
            except _CUPS_ERRORS as exc:
                logger.warning("CUPS queue query failed: %s", exc)
                return False
            time.sleep(1)
        return False

    def _ensure_com_initialized(self):
        if pythoncom is None:
            return
        if not self._com_initialized:
            try:
                pythoncom.CoInitialize()
                self._com_initialized = True
            except RECOVERABLE_ERRORS as e:
                logger.warning("COM初始化警告: %s", e)

    def get_available_printers(self) -> list[dict[str, str]]:
        if not self._is_print_backend_available():
            logger.warning(self._build_unavailable_result()["message"])
            return []
        if win32print is None:
            return self._get_cups_printers()
        try:
            self._ensure_com_initialized()
            printers = []

            try:
                default_printer = win32print.GetDefaultPrinter()
                logger.info("默认打印机: %s", default_printer)
            except Exception:
                default_printer = None
                logger.warning("无法获取默认打印机")

            all_printers = win32print.EnumPrinters(
                win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
            )

            logger.info("找到 %s 个打印机", len(all_printers))

            for printer_info in all_printers:
                logger.info("打印机信息: %s", printer_info)
                logger.info("打印机信息长度: %s", len(printer_info))

                if len(printer_info) >= 3:
                    printer_name = printer_info[2]

                    status = 0
                    if len(printer_info) > 6:
                        status = printer_info[6]
                    elif len(printer_info) > 5:
                        try:
                            status = int(printer_info[5]) if printer_info[5] else 0
                        except Exception:
                            pass

                    status_text = self._get_printer_status(status)

                is_default = printer_name == default_printer

                printers.append(
                    {"name": printer_name, "status": status_text, "is_default": is_default}
                )

                logger.info("  - %s (默认: %s, 状态: %s)", printer_name, is_default, status_text)

            return printers

        except RECOVERABLE_ERRORS as e:
            logger.error("获取打印机列表失败: %s", e, exc_info=True)
            return []

    def _get_printer_status(self, status_code: int) -> str:
        if win32print is None:
            return "不可用"
        status_map = {
            win32print.PRINTER_STATUS_PAUSED: "已暂停",
            win32print.PRINTER_STATUS_ERROR: "错误",
            win32print.PRINTER_STATUS_PENDING_DELETION: "正在删除",
            win32print.PRINTER_STATUS_PAPER_JAM: "卡纸",
            win32print.PRINTER_STATUS_PAPER_OUT: "缺纸",
            win32print.PRINTER_STATUS_MANUAL_FEED: "等待手动送纸",
            win32print.PRINTER_STATUS_PRINTING: "打印中",
            win32print.PRINTER_STATUS_OUTPUT_BIN_FULL: "输出纸盒已满",
            win32print.PRINTER_STATUS_NOT_AVAILABLE: "不可用",
            win32print.PRINTER_STATUS_WAITING: "等待中",
            win32print.PRINTER_STATUS_PROCESSING: "处理中",
            win32print.PRINTER_STATUS_INITIALIZING: "初始化中",
            win32print.PRINTER_STATUS_WARMING_UP: "预热中",
            win32print.PRINTER_STATUS_TONER_LOW: "墨粉不足",
            win32print.PRINTER_STATUS_NO_TONER: "无墨粉",
            win32print.PRINTER_STATUS_PAGE_PUNT: "页面跳过",
            win32print.PRINTER_STATUS_USER_INTERVENTION: "需要用户干预",
            win32print.PRINTER_STATUS_OUT_OF_MEMORY: "内存不足",
            win32print.PRINTER_STATUS_DOOR_OPEN: "前门打开",
            win32print.PRINTER_STATUS_SERVER_UNKNOWN: "服务器未知",
            win32print.PRINTER_STATUS_POWER_SAVE: "节能模式",
        }

        return status_map.get(status_code, "就绪")

    def monitor_print_job(self, printer_name: str, timeout: int = 60) -> bool:
        if not self._is_print_backend_available():
            logger.warning(self._build_unavailable_result()["message"])
            return False
        if win32print is None:
            return self._monitor_cups_print_job(printer_name, timeout)
        try:
            logger.info("开始监控打印机 %s 的打印任务...", printer_name)

            start_time = time.time()

            while time.time() - start_time < timeout:
                try:
                    hPrinter = win32print.OpenPrinter(printer_name)

                    try:
                        jobs = win32print.EnumJobs(hPrinter, 0, -1, 1)

                        if not jobs:
                            logger.info("打印机队列为空，打印任务已完成")
                            return True
                        else:
                            logger.info("打印机队列中有 %s 个任务，等待完成...", len(jobs))
                            for i, job in enumerate(jobs):
                                logger.info("   任务 %s: %s", i + 1, job)
                    finally:
                        win32print.ClosePrinter(hPrinter)

                except RECOVERABLE_ERRORS as e:
                    logger.warning("监控打印任务失败: %s", e)

                time.sleep(1)

            logger.warning("监控打印任务超时（%s秒）", timeout)
            return False

        except RECOVERABLE_ERRORS as e:
            logger.error("监控打印任务时发生错误: %s", e)
            return False

    def print_file(
        self, file_path: str, printer_name: str | None = None, use_default_printer: bool = False
    ) -> dict:
        if not self._is_print_backend_available():
            return self._build_unavailable_result()
        try:
            if not os.path.exists(file_path):
                return {"success": False, "message": f"文件不存在: {file_path}"}

            _, ext = os.path.splitext(file_path)
            ext = ext.lower()

            if not printer_name:
                logger.error("未指定打印机名称，拒绝打印")
                return {"success": False, "message": "未指定打印机名称，无法打印"}

            logger.info("准备打印文件: %s", file_path)
            logger.info("使用打印机: %s", printer_name)

            original_default_printer = None

            if use_default_printer and win32print is not None:
                try:
                    original_default_printer = win32print.GetDefaultPrinter()
                    logger.info("当前默认打印机: %s", original_default_printer)
                    logger.info("目标打印机: %s", printer_name)

                    if original_default_printer != printer_name:
                        logger.info("正在修改默认打印机...")
                        try:
                            win32print.SetDefaultPrinter(printer_name)
                            logger.info("SetDefaultPrinter 调用完成")
                        except RECOVERABLE_ERRORS as e:
                            logger.error("SetDefaultPrinter 调用失败: %s", e)
                            import traceback

                            logger.error(traceback.format_exc())

                        time.sleep(0.5)
                        try:
                            new_default = win32print.GetDefaultPrinter()
                            logger.info("验证 - 当前默认打印机: %s", new_default)
                        except RECOVERABLE_ERRORS as e:
                            logger.error("GetDefaultPrinter 调用失败: %s", e)
                            new_default = original_default_printer

                        if new_default == printer_name:
                            logger.info("默认打印机修改成功: %s", new_default)
                        else:
                            logger.error(
                                "默认打印机修改失败！当前: %s, 目标: %s", new_default, printer_name
                            )
                            try:
                                win32print.SetDefaultPrinter(printer_name)
                                time.sleep(0.5)
                                new_default = win32print.GetDefaultPrinter()
                                logger.info("第二次修改后默认打印机: %s", new_default)
                            except RECOVERABLE_ERRORS as e:
                                logger.error("第二次修改失败: %s", e)
                    else:
                        logger.info("当前默认打印机已经是目标打印机，无需修改")
                except RECOVERABLE_ERRORS as e:
                    logger.error("修改默认打印机失败: %s", e)
                    import traceback

                    logger.error(traceback.format_exc())
            else:
                logger.info("已明确指定打印机，不使用系统默认打印机")

            print_result = None
            try:
                if ext in [".xlsx", ".xls"]:
                    print_result = self._print_excel(file_path, printer_name)
                elif ext == ".pdf":
                    print_result = self._print_pdf(file_path, printer_name)
                else:
                    print_result = self._print_default(file_path, printer_name)

                if print_result.get("success", False):
                    logger.info("打印命令已发送，继续执行后续操作")
            finally:
                if use_default_printer and original_default_printer and win32print is not None:
                    try:
                        if original_default_printer != printer_name:
                            logger.info("恢复默认打印机为: %s", original_default_printer)
                            win32print.SetDefaultPrinter(original_default_printer)
                            logger.info("默认打印机恢复成功")
                    except RECOVERABLE_ERRORS as e:
                        logger.warning("恢复默认打印机失败: %s", e)

            return print_result

        except RECOVERABLE_ERRORS as e:
            logger.error("打印文件失败: %s", e)
            return {"success": False, "message": f"打印失败: {str(e)}"}

    def _print_excel(self, file_path: str, printer_name: str) -> dict:
        if not self._is_print_backend_available():
            return self._build_unavailable_result()
        if win32api is None and not hasattr(os, "startfile"):
            return self._print_excel_macos(file_path, printer_name)
        try:
            logger.info("开始打印Excel文件: %s", file_path)
            logger.info("使用打印机: %s", printer_name)

            try:
                logger.info("方法1: 使用os.startfile打印")
                os.startfile(file_path, "print")
                logger.info("os.startfile打印成功: %s", file_path)
                return {
                    "success": True,
                    "message": "打印任务已发送（os.startfile）",
                    "file": os.path.basename(file_path),
                    "printer": printer_name,
                }
            except RECOVERABLE_ERRORS as e1:
                logger.warning("方法1失败: %s", e1)

                try:
                    logger.info("方法2: 使用ShellExecute print")
                    result = win32api.ShellExecute(0, "print", file_path, None, ".", 1)

                    if result > 32:
                        logger.info("ShellExecute打印成功: %s", file_path)
                        return {
                            "success": True,
                            "message": "打印任务已发送到打印机",
                            "file": os.path.basename(file_path),
                            "printer": printer_name,
                        }
                    else:
                        raise Exception(f"ShellExecute失败，错误代码: {result}")

                except RECOVERABLE_ERRORS as e2:
                    logger.warning("方法2失败: %s", e2)

                    try:
                        logger.info("方法3: 打开文件让用户手动打印")
                        os.startfile(file_path)
                        logger.info("已打开文件: %s", file_path)
                        return {
                            "success": True,
                            "message": "文件已打开，请手动打印",
                            "file": os.path.basename(file_path),
                            "printer": printer_name,
                            "manual": True,
                        }
                    except RECOVERABLE_ERRORS as e3:
                        logger.error("方法3也失败: %s", e3)
                        raise Exception(f"所有打印方法都失败: {e1}; {e2}; {e3}")

        except RECOVERABLE_ERRORS as e:
            logger.error("打印Excel文件失败: %s", e)
            return {"success": False, "message": f"打印失败: {str(e)}"}

    def _print_pdf(self, file_path: str, printer_name: str) -> dict:
        if not self._is_print_backend_available():
            return self._build_unavailable_result()
        if win32print is None:
            return self._print_cups(file_path, printer_name)
        try:
            logger.info("尝试使用win32print直接打印PDF到 %s", printer_name)

            try:
                hprinter = win32print.OpenPrinter(printer_name)

                try:
                    with open(file_path, "rb") as f:
                        file_data = f.read()

                    win32print.StartDocPrinter(hprinter, 1, ("PDF Job", None, "RAW"))
                    win32print.StartPagePrinter(hprinter)
                    win32print.WritePrinter(hprinter, file_data)
                    win32print.EndPagePrinter(hprinter)
                    win32print.EndDocPrinter(hprinter)

                    logger.info("PDF文件已通过win32print发送到打印机: %s", file_path)
                    return {
                        "success": True,
                        "message": "PDF文件已发送到打印机",
                        "file": os.path.basename(file_path),
                        "printer": printer_name,
                        "method": "win32print",
                    }
                finally:
                    win32print.ClosePrinter(hprinter)

            except RECOVERABLE_ERRORS as e:
                logger.warning("win32print打印失败: %s", e)

            logger.info("尝试使用subprocess调用外部程序")
            try:
                import subprocess

                adobe_paths = [
                    r"C:\Program Files (x86)\Adobe\Acrobat Reader DC\Reader\AcroRd32.exe",
                    r"C:\Program Files\Adobe\Acrobat Reader DC\Reader\AcroRd32.exe",
                ]

                for adobe_path in adobe_paths:
                    if os.path.exists(adobe_path):
                        logger.info("使用Adobe Reader: %s", adobe_path)

                        subprocess.run(
                            [adobe_path, "/t", file_path, printer_name],
                            check=True,
                            timeout=30,
                            capture_output=True,
                        )

                        logger.info("PDF文件已通过Adobe Reader发送到打印机")
                        return {
                            "success": True,
                            "message": "PDF文件已通过Adobe Reader发送到打印机",
                            "file": os.path.basename(file_path),
                            "printer": printer_name,
                            "method": "adobe_cli",
                        }

                logger.warning("未找到Adobe Reader")

            except RECOVERABLE_ERRORS as e:
                logger.warning("subprocess方法失败: %s", e)

            raise Exception("所有PDF打印方法都失败")

        except RECOVERABLE_ERRORS as e:
            logger.error("打印PDF文件失败: %s", e)
            return {"success": False, "message": f"打印PDF失败: {str(e)}"}

    def _print_default(self, file_path: str, printer_name: str, show_app: bool = False) -> dict:
        if not self._is_print_backend_available():
            return self._build_unavailable_result()
        if win32api is None:
            return self._print_cups(file_path, printer_name)
        try:
            show_cmd = 1 if show_app else 0

            win32api.ShellExecute(0, "print", file_path, f'/d:"{printer_name}"', ".", show_cmd)

            app_status = "（显示应用窗口）" if show_app else "（隐藏应用窗口）"
            logger.info("文件已发送到打印机%s: %s", app_status, file_path)
            return {
                "success": True,
                "message": f"打印任务已发送到打印机{app_status}",
                "file": os.path.basename(file_path),
                "printer": printer_name,
                "show_app": show_app,
            }

        except RECOVERABLE_ERRORS as e:
            logger.error("打印文件失败: %s", e)
            return {"success": False, "message": f"打印失败: {str(e)}"}

    def get_default_printer(self) -> str | None:
        if not self._is_print_backend_available():
            logger.warning(self._build_unavailable_result()["message"])
            return None
        if win32print is None:
            return self._get_cups_default_printer()
        try:
            return win32print.GetDefaultPrinter()
        except RECOVERABLE_ERRORS as e:
            logger.error("获取默认打印机失败: %s", e)
            return None

    def test_printer(self, printer_name: str) -> dict:
        if not self._is_print_backend_available():
            return self._build_unavailable_result()
        if win32print is None:
            printer = next(
                (item for item in self.get_available_printers() if item["name"] == printer_name),
                None,
            )
            if printer is None:
                return {
                    "success": False,
                    "available": False,
                    "printer": printer_name,
                    "message": "打印机不存在或当前不可用",
                }
            return {
                "success": True,
                "available": True,
                "printer": printer_name,
                "status": printer.get("status") or "未知",
            }
        try:
            hprinter = win32print.OpenPrinter(printer_name)

            printer_info = win32print.GetPrinter(hprinter, 2)
            status = printer_info["Status"]
            status_text = self._get_printer_status(status)

            win32print.ClosePrinter(hprinter)

            return {
                "success": True,
                "available": True,
                "printer": printer_name,
                "status": status_text,
            }

        except RECOVERABLE_ERRORS as e:
            logger.error("测试打印机失败: %s", e)
            return {
                "success": False,
                "available": False,
                "printer": printer_name,
                "message": str(e),
            }

    def get_document_printer(self) -> str | None:
        """获取发货单打印机"""
        if not self._is_print_backend_available():
            logger.warning(self._build_unavailable_result()["message"])
            return None
        try:
            printers = self.get_available_printers()
            if not printers:
                return None

            keywords = [
                "joli",
                "24-pin",
                "dot matrix",
                "impact",
                "lq",
                "针式",
                "hp",
                "canon",
                "epson",
            ]

            for printer in printers:
                name_lower = printer["name"].lower()
                if any(kw in name_lower for kw in keywords):
                    return printer["name"]

            return printers[0]["name"] if printers else None

        except RECOVERABLE_ERRORS as e:
            logger.error("获取发货单打印机失败: %s", e)
            return None

    def get_label_printer(self) -> str | None:
        """获取标签打印机"""
        if not self._is_print_backend_available():
            logger.warning(self._build_unavailable_result()["message"])
            return None
        try:
            printers = self.get_available_printers()
            if not printers:
                return None

            keywords = ["tsc", "ttp", "label", "标签", "thermal", "barcode", "zebra"]

            for printer in printers:
                name_lower = printer["name"].lower()
                if any(kw in name_lower for kw in keywords):
                    return printer["name"]

            return None

        except RECOVERABLE_ERRORS as e:
            logger.error("获取标签打印机失败: %s", e)
            return None
