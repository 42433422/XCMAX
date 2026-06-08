"""JSON HTTP 响应工具（Starlette 基类，保留 werkzeug 风格鸭子类型 API）。

历史上本模块基于 ``werkzeug.wrappers.Response``，下游许多消费点通过
``resp.get_json()`` / ``resp.mimetype`` 读取响应体。为了在不触动这些调用
点的前提下剥离 werkzeug 依赖，本模块导出的 Response 是
``starlette.responses.Response`` 的极小子类，额外暴露：

- ``mimetype``  —— 对应 ``media_type``
- ``get_json(silent=True)`` —— 返回构造时缓存的 dict
"""

from __future__ import annotations

import json
from typing import Any

from starlette.responses import Response


class _JsonResponse(Response):
    """携带原始 JSON 字典的 Starlette Response 子类（werkzeug 风格鸭子类型）。"""

    _json_data: dict[str, Any]

    def __init__(self, data: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False)
        super().__init__(
            content=body,
            status_code=status,
            media_type="application/json",
        )
        # 绕开 Response 的 __slots__/frozen 约定（若有）。
        object.__setattr__(self, "_json_data", data)

    @property
    def mimetype(self) -> str:
        """兼容 werkzeug Response.mimetype。"""
        return self.media_type or ""

    def get_json(self, silent: bool = True) -> dict[str, Any] | None:
        """兼容 werkzeug Response.get_json。``silent`` 仅接受以保持签名一致。"""
        _ = silent
        return getattr(self, "_json_data", None)


def json_response(data: dict[str, Any], status: int = 200) -> _JsonResponse:
    return _JsonResponse(data, status)


def json_response_tuple(data: dict[str, Any], status: int = 200) -> tuple[_JsonResponse, int]:
    return json_response(data, status), status
