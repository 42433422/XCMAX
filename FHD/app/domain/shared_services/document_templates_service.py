"""
兼容性垫片：将原 ``document_templates_service`` 模块重定向到
``app.domain.shared_services.document_templates`` 包。

所有公共符号通过包的 ``__init__.py`` 重新导出，确保现有导入路径不变。
"""

from app.domain.shared_services.document_templates import *  # noqa: F401,F403
from app.domain.shared_services.document_templates import __all__  # noqa: F401
