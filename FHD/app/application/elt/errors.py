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

    def __init__(self, public_message: str):
        super().__init__(public_message)
        self.public_message = public_message


def public_excel_error(exc: Exception) -> str:
    if isinstance(exc, ReviewedExcelError):
        return exc.public_message
    return "文件或请求无法处理，请核对文件、范围和模型配置；结果未知时请勿重复执行"
