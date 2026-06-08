"""Re-export：实现已迁至 app.infrastructure.persistence.compat_db。"""

from app.infrastructure.persistence.compat_db import base as _compat_db_base

# ``import *`` 不会导出以下划线开头的符号；compat 路由依赖这些 helper。
__all__ = [name for name in dir(_compat_db_base) if not name.startswith("__")]
globals().update({name: getattr(_compat_db_base, name) for name in __all__})
