"""XC AGI 在线市场数据库模型（SQLite + SQLAlchemy）。

向后兼容 shim：实体类已迁至 ``modstore_server.db`` 按子域拆分。
"""

from __future__ import annotations

import modstore_server.models_ai_accounts  # noqa: F401,E402
import modstore_server.models_cs  # noqa: F401,E402
from modstore_server.db.base import (  # noqa: F401
    Base,
    _add_column_if_missing,
    _engine,
    _SessionFactory,
    _sqlite_add_column_if_missing,
    database_url,
    default_db_path,
    get_engine,
    get_session_factory,
    init_db,
    init_default_plan_templates,
)
from modstore_server.db.billing import *  # noqa: F403,F401
from modstore_server.db.catalog import *  # noqa: F403,F401
from modstore_server.db.dev_platform import *  # noqa: F403,F401
from modstore_server.db.employee_ops import *  # noqa: F403,F401
from modstore_server.db.eskill import *  # noqa: F403,F401
from modstore_server.db.identity import *  # noqa: F403,F401
from modstore_server.db.knowledge import *  # noqa: F403,F401
from modstore_server.db.llm_chat import *  # noqa: F403,F401
from modstore_server.db.openapi import *  # noqa: F403,F401
from modstore_server.db.ops_events import *  # noqa: F403,F401
from modstore_server.db.scheduler_ops import *  # noqa: F403,F401
from modstore_server.db.studio_assets import *  # noqa: F403,F401
from modstore_server.db.workflow import *  # noqa: F403,F401
