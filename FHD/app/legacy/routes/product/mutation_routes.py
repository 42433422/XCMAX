"""Product writes dispatched through the governed Agent workflow."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Body, Request
from fastapi.responses import JSONResponse

from .mutation_flow import ProductMutations


class ProductMutationRoutes:
    """Product writes dispatched through the governed Agent workflow."""

    def __init__(self, *, mutations: Callable[[], ProductMutations]) -> None:
        router = self.router = APIRouter()

        @router.post("/products/update", response_model=None)
        @router.post("/products/update/", response_model=None, include_in_schema=False)
        def products_update(
            request: Request, body: dict = Body(default_factory=dict)
        ) -> dict[str, Any] | JSONResponse:
            return mutations().submit(request, body, action="update", route_path="/products/update")

        self.products_update = products_update

        @router.post("/products/add", response_model=None)
        @router.post("/products/add/", response_model=None, include_in_schema=False)
        def products_add(
            request: Request, body: dict = Body(default_factory=dict)
        ) -> dict[str, Any] | JSONResponse:
            return mutations().submit(request, body, action="create", route_path="/products/add")

        self.products_add = products_add

        @router.post("/products/delete", response_model=None)
        @router.post("/products/delete/", response_model=None, include_in_schema=False)
        def products_delete(
            request: Request, body: dict = Body(default_factory=dict)
        ) -> dict[str, Any] | JSONResponse:
            return mutations().submit(request, body, action="delete", route_path="/products/delete")

        self.products_delete = products_delete

        @router.post("/products/batch-delete", response_model=None)
        @router.post("/products/batch-delete/", response_model=None, include_in_schema=False)
        def products_batch_delete(
            request: Request, body: dict = Body(default_factory=dict)
        ) -> dict[str, Any] | JSONResponse:
            return mutations().submit(
                request, body, action="batch_delete", route_path="/products/batch-delete"
            )

        self.products_batch_delete = products_batch_delete
