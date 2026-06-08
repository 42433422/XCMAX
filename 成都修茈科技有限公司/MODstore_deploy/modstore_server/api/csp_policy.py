"""Content-Security-Policy string builders for SecurityHeadersMiddleware."""

from __future__ import annotations


def _common_directives() -> str:
    return (
        "default-src 'self'; "
        "img-src 'self' data: blob: https:; "
        "font-src 'self' data:; "
        "connect-src 'self' ws: wss: https:; "
        "frame-ancestors 'none'"
    )


def build_enforced_csp(nonce: str) -> str:
    """Production CSP: no unsafe-eval; script via nonce + self; styles still allow inline (Vue/libs)."""
    n = nonce.replace("'", "")
    return (
        f"{_common_directives()}; "
        f"script-src 'self' 'nonce-{n}'; "
        "style-src 'self' 'unsafe-inline'"
    )


def build_swagger_csp() -> str:
    """Swagger / ReDoc need inline scripts until bundled separately."""
    return (
        f"{_common_directives()}; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
        "style-src 'self' 'unsafe-inline'"
    )


def build_report_only_strict_csp() -> str:
    """Stricter policy for Report-Only: probe removal of style unsafe-inline."""
    return (
        f"{_common_directives()}; "
        "script-src 'self'; "
        "style-src 'self'; "
        "report-uri /api/csp-report"
    )
