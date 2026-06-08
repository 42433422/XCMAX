@echo off
chcp 65001 >nul
echo ========================================
echo   MODstore 市场部署脚本
echo ========================================
echo.

echo [1/3] 检查 Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Python，请先安装 Python 3.11+
    pause
    exit /b 1
)
echo [OK] Python 已安装

echo.
echo [2/3] 安装依赖...
pip install fastapi uvicorn python-multipart httpx sqlalchemy PyJWT bcrypt -q
if errorlevel 1 (
    echo [错误] 依赖安装失败
    pause
    exit /b 1
)
echo [OK] 依赖安装完成

echo.
echo [3/3] 启动服务...
echo.
echo 请访问: http://localhost:8765/market
echo API 文档: http://localhost:8765/docs
echo.
echo 按 Ctrl+C 停止服务
echo.

set MODSTORE_ADMIN_RECHARGE_TOKEN=your-secret-token-here
python -m uvicorn modstore_server.app:app --host 0.0.0.0 --port 8765
