"""
⚠️ DEPRECATED: Flask 应用工厂已弃用

本模块已迁移到 FastAPI，请使用:
  cd XCAGI
  python run.py
  
历史代码已归档至: .archive/flask-app-factory-2026-04/

如需查看原始代码:
  - app___init__py.bak (原 Flask 应用工厂)
  - app_extensions_py.bak (原 Flask 扩展管理)
  - app_control_routes_py.bak (原 Control 路由)
"""

import logging

logger = logging.getLogger(__name__)

def create_app(*args, **kwargs):
    """
    ⚠️ 此函数已弃用
    
    迁移说明:
    - Flask → FastAPI 迁移已完成
    - 路由位于仓库根 app/fastapi_routes/（XCAGI/app 为指向该目录的符号链接时路径等价）
    - Control 路由：app/fastapi_routes/control.py

    请使用 XCAGI FastAPI 入口启动应用。
    """
    raise RuntimeError(
        "Flask 应用已弃用。请使用 XCAGI FastAPI 入口: "
        "cd XCAGI && python run.py"
    )
