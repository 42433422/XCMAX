from __future__ import annotations

import logging
import os
import time
from collections import defaultdict

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger(__name__)

_EXEMPT_PATHS = {"/health", "/metrics", "/docs", "/openapi.json", "/redoc"}
_DEFAULT_LIMIT = 60
_DEFAULT_WINDOW = 60
# 设计为长轮询/高频查询的 GET 端点，在 RateLimiterMiddleware 内使用更高上限。
# 命中条件：method == GET 且 path 以前缀开头（含子路径）。
# 这些端点都是「内存读」+「只读」语义，对后端开销极低，但客户端会以 0.5~2s 的频率轮询，
# 在默认 60/min 限额下极易出现误伤性 429（参见工作台「开始生成员工包」轮询）。
_HIGH_RATE_GET_PREFIXES: tuple[str, ...] = (
    "/api/workbench/sessions/",
    # 市场目录/分面：只读 + Redis 缓存，页面切换会连续 GET，且反代后多用户常共用一个 IP。
    "/api/market/catalog",
    "/api/market/facets",
)
# 流式 TTS 会在一轮回复内连续 POST 多句；单独提高上限，避免 60/min 误伤。
_HIGH_RATE_POST_PREFIXES: tuple[str, ...] = ("/api/workbench/tts/",)
_HIGH_RATE_DEFAULT_LIMIT = 600


class _InMemoryBucket:
    def __init__(self):
        self._windows: dict[str, list[float]] = defaultdict(list)

    def check(self, key: str, limit: int, window: int) -> tuple[bool, int]:
        """Return ``(allowed, retry_after_seconds)``.

        ``retry_after_seconds`` is 0 when the request is allowed.
        """
        now = time.time()
        cutoff = now - window
        self._windows[key] = [t for t in self._windows[key] if t > cutoff]
        if len(self._windows[key]) >= limit:
            oldest = min(self._windows[key]) if self._windows[key] else now
            return False, max(1, int(oldest + window - now))
        self._windows[key].append(now)
        return True, 0


class _RedisBucket:
    def __init__(self, redis_url: str):
        import redis

        self._client = redis.from_url(redis_url, decode_responses=True)
        # Single Lua script handles both the rate-limit decision AND the
        # Retry-After calculation so that a denied request costs exactly 1
        # Redis round-trip instead of the previous 2 (EVALSHA + ZRANGE).
        self._lua_check = self._client.register_script(
            """
            local key    = KEYS[1]
            local now    = tonumber(ARGV[1])
            local window = tonumber(ARGV[2])
            local limit  = tonumber(ARGV[3])

            redis.call('ZREMRANGEBYSCORE', key, 0, now - window)
            local count = redis.call('ZCARD', key)
            if count < limit then
                redis.call('ZADD', key, now, tostring(now))
                redis.call('EXPIRE', key, window)
                return {1, 0}
            end
            -- denied: fetch oldest entry score for Retry-After (no extra round-trip)
            local pair = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
            local oldest = 0
            if #pair >= 2 then
                oldest = tonumber(pair[2])
            end
            return {0, oldest}
        """
        )

    def check(self, key: str, limit: int, window: int) -> tuple[bool, int]:
        """Return ``(allowed, retry_after_seconds)``.

        ``retry_after_seconds`` is 0 when the request is allowed.
        Single Redis round-trip in both the allowed and denied paths.
        """
        now = time.time()
        result = self._lua_check(keys=[key], args=[now, window, limit])
        allowed = bool(result[0])
        if allowed:
            return True, 0
        oldest = float(result[1]) if result[1] else 0.0
        retry = max(1, int(oldest + window - now)) if oldest else 1
        return False, retry


def _client_ip(request: Request) -> str:
    forwarded = (request.headers.get("x-forwarded-for") or "").strip()
    if forwarded:
        return forwarded.split(",", 1)[0].strip()[:64] or "unknown"
    if request.client and request.client.host:
        return request.client.host[:64]
    return "unknown"


class RateLimiterMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self._limit = int(os.environ.get("MODSTORE_RATE_LIMIT", str(_DEFAULT_LIMIT)))
        self._window = int(os.environ.get("MODSTORE_RATE_WINDOW", str(_DEFAULT_WINDOW)))
        # 高频 GET 端点（轮询）单独的上限。env 留出运维微调入口；不得低于全局 limit，
        # 否则就退化成 max(global, configured)，避免「调低反而放宽」的反直觉行为。
        configured_high = int(
            os.environ.get("MODSTORE_RATE_LIMIT_HIGH", str(_HIGH_RATE_DEFAULT_LIMIT))
        )
        self._high_rate_limit = max(self._limit, configured_high)
        self._bucket = self._init_bucket()

    def _resolve_limit(self, method: str, path: str) -> int:
        if method == "GET":
            for prefix in _HIGH_RATE_GET_PREFIXES:
                if path.startswith(prefix):
                    return self._high_rate_limit
        if method == "POST":
            for prefix in _HIGH_RATE_POST_PREFIXES:
                if path.startswith(prefix):
                    return self._high_rate_limit
        return self._limit

    def _init_bucket(self):
        redis_url = os.environ.get("MODSTORE_REDIS_URL", "").strip()
        if redis_url:
            try:
                bucket = _RedisBucket(redis_url)
                bucket._client.ping()
                return bucket
            except Exception:
                logger.warning("Redis unavailable, falling back to in-memory rate limiter")
        return _InMemoryBucket()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive, send)
        path = request.url.path

        for exempt in _EXEMPT_PATHS:
            if path == exempt or path.startswith(exempt + "/"):
                await self.app(scope, receive, send)
                return

        client_ip = _client_ip(request)
        user_hint = (
            request.headers.get("x-modstore-user") or request.headers.get("x-user-id") or ""
        )[:64]
        route = f"{request.method}:{path}"[:220]
        key = f"rate:{client_ip}:{user_hint}:{route}"
        limit = self._resolve_limit(request.method, path)

        allowed, retry_after = self._bucket.check(key, limit, self._window)
        if not allowed:
            response = JSONResponse(
                {"detail": "Too many requests"},
                status_code=429,
                headers={"Retry-After": str(retry_after)},
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)
