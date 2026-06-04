"""
structured_logging.py — 结构化 JSON 日志（NDJSON，单行 JSON）

替代散落各处的 ``logging.basicConfig(format="%(asctime)s - %(name)s - %(message)s")``。

设计目标
========
1. **零外部依赖**：纯 stdlib NDJSON，输出形态等价 python-json-logger
2. **NDJSON 单行**：与 K8s / Loki / Vector / Promtail 友好
3. **结构化字段**：timestamp / level / logger / message + extras
4. **向后兼容**：保留 setup_logging() 字符串格式选项
5. **可观测性**：自动注入 trace_id / span_id（OTel 可选）

输出格式
========
每行一条记录，例如：
    {"ts":"2026-06-02T10:30:45.123Z","level":"INFO","logger":"app.main","msg":"started","pid":12345,"module":"main","line":42}

启用方式
========
    from app.utils.structured_logging import setup_structured_logging
    setup_structured_logging()  # 默认 INFO 级别
    setup_structured_logging(level="DEBUG", service="xcagi-api")

或通过环境变量：
    LOG_FORMAT=json  # 启用 JSON（默认）
    LOG_FORMAT=text  # 退回传统字符串
    LOG_LEVEL=DEBUG
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any


_RESERVED = {
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName",
    "processName", "process", "message", "asctime", "taskName",
}


class NDJSONFormatter(logging.Formatter):
    """结构化 JSON 日志格式化器（单行 NDJSON）"""

    def __init__(self, *, service: str | None = None, env: str | None = None) -> None:
        super().__init__()
        self._service = service or os.environ.get("SERVICE_NAME", "xcagi")
        self._env = env or os.environ.get("APP_ENV", "development")
        # 主机名（缓存避免重复）
        self._hostname = os.uname().nodename if hasattr(os, "uname") else "unknown"

    def format(self, record: logging.LogRecord) -> str:
        # 基础字段
        payload: dict[str, Any] = {
            "ts": self._iso_timestamp(record.created),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "service": self._service,
            "env": self._env,
            "host": self._hostname,
            "pid": record.process,
            "module": record.module,
            "func": record.funcName,
            "line": record.lineno,
        }

        # 异常信息
        if record.exc_info:
            payload["exc_type"] = record.exc_info[0].__name__ if record.exc_info[0] else None
            payload["exc"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack"] = self.formatStack(record.stack_info)

        # 透传 extras（logger.info("x", extra={"user_id": 42})）
        for key, value in record.__dict__.items():
            if key in _RESERVED or key.startswith("_"):
                continue
            try:
                json.dumps(value)
                payload[key] = value
            except (TypeError, ValueError):
                payload[key] = repr(value)

        # OTel 上下文（如果存在）
        for otel_attr in ("trace_id", "span_id"):
            val = getattr(record, otel_attr, None)
            if val is not None:
                payload[otel_attr] = val

        try:
            return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        except (TypeError, ValueError) as e:
            # 兜底：极端情况下序列化失败
            return json.dumps(
                {
                    **payload,
                    "msg": payload["msg"][:200],
                    "serialization_error": str(e),
                },
                ensure_ascii=False,
            )

    @staticmethod
    def _iso_timestamp(epoch_seconds: float) -> str:
        """ISO 8601 with UTC timezone + ms precision"""
        dt = datetime.fromtimestamp(epoch_seconds, tz=timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{int(dt.microsecond / 1000):03d}Z"


class TextFormatter(logging.Formatter):
    """传统字符串格式（fallback / 调试用）"""

    DEFAULT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    def __init__(self, fmt: str | None = None) -> None:
        super().__init__(fmt or self.DEFAULT)


def setup_structured_logging(
    level: str | None = None,
    *,
    service: str | None = None,
    force_json: bool | None = None,
) -> None:
    """
    配置根日志器为结构化 JSON 输出。

    Args:
        level: 日志级别（默认读 LOG_LEVEL env，INFO）
        service: 服务名（默认读 SERVICE_NAME env，'xcagi'）
        force_json: True 强制 JSON；False 强制文本；None 读 LOG_FORMAT env
    """
    # 1. 决定日志格式
    if force_json is None:
        fmt = os.environ.get("LOG_FORMAT", "json").lower()
        force_json = fmt == "json"

    # 2. 决定日志级别
    if level is None:
        level = os.environ.get("LOG_LEVEL", "INFO")
    numeric_level = getattr(logging, level.upper(), logging.INFO)

    # 3. 清除已有 handler（避免重复输出）
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)

    # 4. 添加新 handler
    handler = logging.StreamHandler(sys.stdout)
    if force_json:
        handler.setFormatter(NDJSONFormatter(service=service))
    else:
        handler.setFormatter(TextFormatter())
    root.addHandler(handler)
    root.setLevel(numeric_level)

    # 5. 抑制过于啰嗦的库
    for noisy in ("uvicorn.access", "sqlalchemy.engine", "httpx"):
        logging.getLogger(noisy).setLevel(max(numeric_level, logging.WARNING))


def is_json_logging_active() -> bool:
    """检查当前根 logger 是否使用 NDJSON 格式化器（用于运行时判断）"""
    root = logging.getLogger()
    for h in root.handlers:
        if isinstance(h.formatter, NDJSONFormatter):
            return True
    return False


# 便捷别名（兼容旧代码 import）
def get_logger(name: str | None = None) -> logging.Logger:
    """获取 logger，自动附加常用 extras 字段。"""
    return logging.getLogger(name)
