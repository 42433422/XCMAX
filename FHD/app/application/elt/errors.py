from __future__ import annotations


class EltError(RuntimeError):
    def __init__(self, code: str, message: str, *, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class EltNotFound(EltError):
    def __init__(self, resource: str):
        super().__init__("ELT_NOT_FOUND", f"{resource}不存在或无权访问", status_code=404)


class EltConflict(EltError):
    def __init__(self, code: str, message: str):
        super().__init__(code, message, status_code=409)


class ReviewedExcelError(ValueError):
    """A validation message authored by the reviewed Excel boundary, safe for users."""

    provider_status: int | None = None

    def __init__(self, public_message: str, *, provider_status: int | None = None):
        super().__init__(public_message)
        self.public_message = public_message
        self.provider_status = provider_status


def provider_http_status(exc: BaseException | None) -> int | None:
    """Best-effort HTTP status from provider failures, including wrapped causes."""
    import re

    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        for attr in ("provider_status", "status_code"):
            raw = getattr(current, attr, None)
            try:
                code = int(raw) if raw is not None else None
            except (TypeError, ValueError):
                code = None
            if code is not None and 400 <= code <= 599:
                return code
        match = re.search(r"平台错误\((\d{3})\)", str(current))
        if match:
            return int(match.group(1))
        current = current.__cause__ or current.__context__
    return None


def is_definite_provider_failure(exc: Exception) -> bool:
    """True when the provider answered with a terminal client/config error."""
    return provider_http_status(exc) in {400, 401, 402, 403, 404}


def public_excel_error(exc: Exception) -> str:
    if isinstance(exc, ReviewedExcelError):
        return exc.public_message
    return "文件或请求无法处理，请核对文件、范围和模型配置；结果未知时请勿重复执行"
