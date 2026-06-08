@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul

REM =============================================================================
REM  XCAGI 桌面后端（SQLite 本地库，与安装包 --desktop 一致）
REM  不依赖 Docker/PostgreSQL。Web/Postgres 开发请用 xcagi-backend.cmd 或 start-xcagi.bat
REM =============================================================================

cd /d "%~dp0"
set "XCAGI_DIR=%CD%"
if "%XCAGI_DIR:~-1%"=="\" set "XCAGI_DIR=%XCAGI_DIR:~0,-1%"
pushd "%XCAGI_DIR%\.."
set "FHD_ROOT=%CD%"
popd

if not defined XCAGI_PRODUCT_SKU set "XCAGI_PRODUCT_SKU=enterprise"
if not defined XCAGI_DATA_DIR set "XCAGI_DATA_DIR=%XCAGI_DIR%\data\desktop-dev"
if not defined XCAGI_MODS_ROOT set "XCAGI_MODS_ROOT=%FHD_ROOT%\mods"

set "XCAGI_DESKTOP_MODE=1"
set "XCAGI_PRODUCT_SKU_FILE=%FHD_ROOT%\desktop\resources"
set "XCAGI_MOD_ISOLATED_DATABASES=0"
set "XCAGI_DESKTOP_FORCE_LOCAL_DATABASE=1"
set "XCAGI_FORCE_SYNC_TASKS=1"
set "PYTHONUTF8=1"
set "FASTAPI_HOST=127.0.0.1"
set "XCAGI_API_HOST=127.0.0.1"
if not defined XCAGI_UVICORN_RELOAD set "XCAGI_UVICORN_RELOAD=1"

REM 避免 shell 预置或旧会话中的 Postgres URL 干扰；run_fastapi --desktop 会写入 SQLite
set "DATABASE_URL="
set "VECTOR_DB_URL="
set "XCAGI_DESKTOP_KEEP_DATABASE_URL="

if exist "%FHD_ROOT%\.venv\Scripts\python.exe" (
    set "PY_EXE=%FHD_ROOT%\.venv\Scripts\python.exe"
) else if exist "%XCAGI_DIR%\.venv\Scripts\python.exe" (
    set "PY_EXE=%XCAGI_DIR%\.venv\Scripts\python.exe"
) else (
    set "PY_EXE=python"
)

if not exist "%XCAGI_DATA_DIR%\data" mkdir "%XCAGI_DATA_DIR%\data" 2>nul

echo [INFO] xcagi-backend-desktop: SKU=%XCAGI_PRODUCT_SKU%
echo [INFO] xcagi-backend-desktop: XCAGI_DATA_DIR=%XCAGI_DATA_DIR%
echo [INFO] xcagi-backend-desktop: SQLite via run_fastapi.py --desktop
echo [INFO] Health: http://127.0.0.1:5000/api/health
echo [INFO] Docs:   http://127.0.0.1:5000/docs
echo [INFO] =================================================================

"%PY_EXE%" run_fastapi.py --desktop --headless --host 127.0.0.1 --port 5000 --data-dir "%XCAGI_DATA_DIR%"
set "RC=%ERRORLEVEL%"
if "%RC%"=="3221225786" exit /b 0
if not "%RC%"=="0" (
    echo [ERROR] Desktop backend exited with code %RC%.
    pause
    exit /b %RC%
)
exit /b 0
