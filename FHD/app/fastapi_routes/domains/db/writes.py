"""Re-export：实现已迁至 app.infrastructure.persistence.compat_db。"""

from app.infrastructure.persistence.compat_db import writes as _compat_db_writes

__all__ = [name for name in dir(_compat_db_writes) if not name.startswith("__")]
globals().update({name: getattr(_compat_db_writes, name) for name in __all__})
