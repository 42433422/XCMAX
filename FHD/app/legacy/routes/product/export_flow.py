"""Guard price-list rendering and share the two public document aliases."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from fastapi import HTTPException, Request
from fastapi.responses import Response

from .port_contracts import BusinessVisibility, Payload


@dataclass(frozen=True)
class ProductExports:
    verify_read: Callable[[Request], None]
    word_response: Callable[[str | None, str | None, str | None, str | None], Response]
    visibility_factory: Callable[[], BusinessVisibility]
    preview_factory: Callable[[], Callable[[str | None], Payload]]

    def document(
        self,
        request: Request,
        unit: str | None,
        keyword: str | None,
        export_date: str | None,
        template_id: str | None,
    ) -> Response:
        self.verify_read(request)
        return self.word_response(unit, keyword, export_date, template_id)

    def preview(self, request: Request, template_id: str | None) -> Payload:
        build_preview = self.preview_factory()
        self.verify_read(request)
        visibility = self.visibility_factory()
        if not visibility.business_data_exposed():
            raise HTTPException(
                status_code=503,
                detail=visibility.business_data_hidden_reason() or "扩展 Mod 未就绪。",
            )
        return build_preview(template_id)
