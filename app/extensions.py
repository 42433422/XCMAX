"""
⚠️ DEPRECATED: Flask 扩展管理已弃用

本模块已迁移到 FastAPI，请使用:
  cd XCAGI
  python run.py
  
历史代码已归档至: .archive/flask-app-factory-2026-04/app_extensions_py.bak
"""

import logging
from functools import wraps

logger = logging.getLogger(__name__)


class _ImmediateResult:
    def __init__(self, value=None):
        self.id = "desktop-immediate"
        self.value = value

    def get(self, timeout=None):
        return self.value


class DummyCelery:
    """Import-compatible Celery replacement for FastAPI/desktop mode."""

    def task(self, *dargs, **dkwargs):
        def decorator(func):
            @wraps(func)
            def wrapper(*args, **kwargs):
                return func(*args, **kwargs)

            wrapper.delay = lambda *args, **kwargs: _ImmediateResult(func(*args, **kwargs))
            wrapper.apply_async = lambda args=None, kwargs=None, **_: _ImmediateResult(
                func(*(args or ()), **(kwargs or {}))
            )
            return wrapper

        if dargs and callable(dargs[0]) and not dkwargs:
            return decorator(dargs[0])
        return decorator

    def send_task(self, name, args=None, kwargs=None, **_options):
        logger.warning("Celery 不可用，任务 %s 已在桌面/同步模式下跳过远程队列", name)
        return _ImmediateResult()


celery_app = DummyCelery()

def init_extensions(app):
    """
    ⚠️ 此函数已弃用
    
    FastAPI 使用不同的扩展管理方式，不需要 Flask-Caching/Celery 初始化。
    请使用 XCAGI FastAPI 入口启动应用。
    """
    raise RuntimeError(
        "Flask 扩展已弃用。请使用 XCAGI FastAPI 入口: "
        "cd XCAGI && python run.py"
    )
