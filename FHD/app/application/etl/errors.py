from __future__ import annotations


class EtlError(RuntimeError):
    def __init__(self, code: str, message: str, *, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class EtlNotFound(EtlError):
    def __init__(self, resource: str):
        super().__init__("ETL_NOT_FOUND", f"{resource}不存在或无权访问", status_code=404)


class EtlConflict(EtlError):
    def __init__(self, code: str, message: str):
        super().__init__(code, message, status_code=409)
