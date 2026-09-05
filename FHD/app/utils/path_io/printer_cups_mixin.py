"""CUPS and safe-path support for :class:`PrinterUtils`."""

from __future__ import annotations

from typing import Any, BinaryIO, cast


def _facade() -> Any:
    from app.utils.path_io import print_utils

    return print_utils


class PrinterCupsMixin:
    @staticmethod
    def _is_print_backend_available() -> bool:
        return bool(
            _facade()._PRINT_BACKEND_AVAILABLE
            or _facade().PrinterUtils._is_cups_backend_available()
        )

    @staticmethod
    def _is_cups_backend_available() -> bool:
        return (
            _facade().sys.platform == "darwin"
            and _facade().win32print is None
            and (_facade().win32api is None)
            and _facade().os.path.isfile(_facade()._CUPS_LPSTAT)
            and _facade().os.access(_facade()._CUPS_LPSTAT, _facade().os.X_OK)
            and _facade().os.path.isfile(_facade()._CUPS_LP)
            and _facade().os.access(_facade()._CUPS_LP, _facade().os.X_OK)
        )

    def _build_unavailable_result(self) -> dict:
        if _facade().sys.platform == "darwin":
            detail = "未找到 macOS CUPS 命令 lpstat/lp"
        else:
            detail = f"缺少 Windows 打印依赖：{_facade()._PRINT_BACKEND_ERROR or 'unknown'}"
        message = f"当前环境不支持打印功能（{detail}）"
        return {"success": False, "message": message}

    @staticmethod
    def _cups_env() -> dict[str, str]:
        return {**_facade().os.environ, "LC_ALL": "C", "LANG": "C"}

    @classmethod
    def _run_cups(
        cls,
        command: str,
        arguments: tuple[str, ...],
        *,
        timeout: float = 15,
        input_stream: BinaryIO | None = None,
    ) -> Any:
        if command == "lp":
            executable = _facade()._CUPS_LP
        elif command == "lpstat":
            executable = _facade()._CUPS_LPSTAT
        else:
            raise ValueError("unsupported CUPS command")
        return _facade().subprocess.run(
            [executable, *arguments],
            stdin=input_stream,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env=cls._cups_env(),
        )

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
        except _facade()._CUPS_ERRORS as exc:
            _facade().logger.warning("CUPS default printer query failed: %s", exc)
        return None

    @staticmethod
    def _cups_status_text(raw: str) -> str:
        normalized = raw.lower()
        if "disabled" in normalized or "paused" in normalized or "已停用" in raw or ("暂停" in raw):
            return "已暂停"
        if (
            "printing" in normalized
            or "processing" in normalized
            or "正在打印" in raw
            or ("正在处理" in raw)
        ):
            return "打印中"
        if "idle" in normalized or "enabled" in normalized or "闲置" in raw:
            return "就绪"
        return "未知"

    @classmethod
    def _parse_cups_printer_line(cls, line: str) -> tuple[str, str] | None:
        if line.startswith("printer "):
            parts = line.split(maxsplit=2)
            if len(parts) >= 2:
                return (parts[1], cls._cups_status_text(parts[2] if len(parts) == 3 else ""))
            return None
        if line.startswith("打印机"):
            body = line[len("打印机") :]
            markers = ("正在打印", "正在处理", "已停用", "暂停", "闲置")
            positions = [(body.find(marker), marker) for marker in markers if body.find(marker) > 0]
            if positions:
                (index, marker) = min(positions, key=lambda item: item[0])
                return (body[:index].strip(), cls._cups_status_text(marker))
        return None

    def _get_cups_printers(self) -> list[dict[str, str | bool]]:
        try:
            result = self._run_cups("lpstat", ("-p",))
            if result.returncode != 0:
                _facade().logger.warning("CUPS printer query failed: %s", result.stderr.strip())
                return []
            default_printer = self._get_cups_default_printer()
            printers: list[dict[str, str | bool]] = []
            for raw_line in result.stdout.splitlines():
                line = raw_line.strip()
                parsed = self._parse_cups_printer_line(line)
                if parsed is None:
                    continue
                (name, status) = parsed
                printers.append(
                    {"name": name, "status": status, "is_default": name == default_printer}
                )
            return printers
        except _facade()._CUPS_ERRORS as exc:
            _facade().logger.error("CUPS printer discovery failed: %s", exc)
            return []

    def _resolve_cups_printer_name(self, requested: str) -> str | None:
        if not _facade()._CUPS_PRINTER_NAME_RE.fullmatch(requested):
            return None
        for printer in self._get_cups_printers():
            candidate = str(printer.get("name") or "")
            if candidate == requested and _facade()._CUPS_PRINTER_NAME_RE.fullmatch(candidate):
                return candidate
        return None

    @staticmethod
    def _allowed_print_roots() -> tuple[str, ...]:
        from app.utils.path_io.path_utils import get_app_data_dir

        app_data = _facade().os.path.realpath(get_app_data_dir())
        roots = {
            app_data,
            _facade().os.path.join(app_data, "shipment_outputs"),
            _facade().os.path.realpath(_facade().tempfile.gettempdir()),
        }
        configured = _facade().os.environ.get("XCAGI_PRINT_ALLOWED_ROOTS", "")
        for value in configured.split(_facade().os.pathsep):
            value = value.strip()
            if value:
                roots.add(_facade().os.path.realpath(value))
        return tuple(sorted(roots))

    @classmethod
    def _resolve_allowed_print_path(cls, file_path: str) -> str | None:
        from app.infrastructure.printing.label_pdf_printer import is_label_job_location

        # Managed label jobs can only enter the spooler through their atomic dispatch guard.
        if is_label_job_location(file_path):
            return None
        requested = _facade().os.path.realpath(_facade().os.path.abspath(file_path))
        for root in cls._allowed_print_roots():
            normalized_root = _facade().os.path.realpath(root)
            try:
                with _facade().os.scandir(normalized_root) as entries:
                    for entry in entries:
                        if not entry.is_file(follow_symlinks=False):
                            continue
                        candidate = _facade().os.path.realpath(entry.path)
                        if _facade().os.path.normcase(candidate) == _facade().os.path.normcase(
                            requested
                        ):
                            return cast(str, candidate)
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
                    "lp", ("-d", validated_printer), timeout=30, input_stream=source
                )
            if result.returncode != 0:
                _facade().logger.warning(
                    "CUPS rejected print job for %s: %s",
                    validated_printer,
                    result.stderr.strip() or result.stdout.strip() or "lp command failed",
                )
                return {
                    "success": False,
                    "message": "打印失败：macOS 打印服务拒绝了任务",
                    "printer": validated_printer,
                }
            return {
                "success": True,
                "message": "打印任务已提交到 macOS CUPS",
                "file": _facade().os.path.basename(validated_file),
                "printer": validated_printer,
                "method": "cups_lp",
            }
        except _facade()._CUPS_ERRORS as exc:
            _facade().logger.error("CUPS print failed: %s", exc)
            return {
                "success": False,
                "message": "打印失败：macOS 打印服务暂不可用",
                "printer": validated_printer,
            }

    def _monitor_cups_print_job(self, printer_name: str, timeout: int) -> bool:
        validated_printer = self._resolve_cups_printer_name(printer_name)
        if validated_printer is None:
            return False
        start_time = _facade().time.time()
        while _facade().time.time() - start_time < timeout:
            try:
                result = self._run_cups("lpstat", ("-o", validated_printer))
                if result.returncode == 0 and (not result.stdout.strip()):
                    return True
            except _facade()._CUPS_ERRORS as exc:
                _facade().logger.warning("CUPS queue query failed: %s", exc)
                return False
            _facade().time.sleep(1)
        return False
