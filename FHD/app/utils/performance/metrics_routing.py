"""Pure, bounded route classification for business SLI metrics."""


def customer_operation(method: str, path: str) -> str | None:
    normalized = path.rstrip("/").lower()
    if not normalized.startswith("/api/customers"):
        return None
    if normalized.endswith("/batch-delete") or method.upper() == "DELETE":
        return "delete"
    if method.upper() in {"PUT", "PATCH"}:
        return "update"
    if method.upper() == "POST":
        return "create"
    return "query"


def document_type(path: str) -> str | None:
    normalized = path.lower()
    if "/ocr" in normalized:
        return "ocr"
    if "/etl" in normalized or "/import/" in normalized or normalized.endswith("/import"):
        return "excel"
    if "/documents/upload" in normalized:
        return "document"
    return None


def export_type(path: str) -> str | None:
    normalized = path.lower()
    if "/export" not in normalized and not normalized.endswith((".xlsx", ".docx", ".pdf")):
        return None
    if ".pdf" in normalized:
        return "pdf"
    if ".docx" in normalized:
        return "docx"
    if ".csv" in normalized:
        return "csv"
    return "excel"


def mod_operation(path: str) -> str | None:
    normalized = path.rstrip("/").lower()
    if "/mod-store/" not in normalized:
        return None
    for operation in ("uninstall", "deactivate", "activate", "install", "update"):
        if normalized.endswith(f"/{operation}"):
            return "install" if operation == "update" else operation
    return None
