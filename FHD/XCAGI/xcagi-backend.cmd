@echo off
setlocal EnableExtensions EnableDelayedExpansion

REM =============================================================================
REM  XCAGI Backend Launcher (Updated for FastAPI Migration)
REM =============================================================================
REM  CHANGELOG:
REM    2026-04-19: Renamed from xcagi-backend-8000.cmd to xcagi-backend.cmd
REM                Port 5000 (FastAPI unified entry)
REM                Now uses: uvicorn app.fastapi_app:get_fastapi_app --port 5000
REM =============================================================================

cd /d "%~dp0"
set "XCAGI_ROOT=%CD%"
if "%XCAGI_ROOT:~-1%"=="\" set "XCAGI_ROOT=%XCAGI_ROOT:~0,-1%"
pushd "%XCAGI_ROOT%\.."
set "FHD_ROOT=%CD%"
popd

REM Ensure mods root is set for proper mod loading
if not defined XCAGI_MODS_ROOT (
  set "XCAGI_MODS_ROOT=%FHD_ROOT%\mods"
)

echo [INFO] xcagi-backend.cmd: XCAGI_ROOT=%XCAGI_ROOT%
echo [INFO] xcagi-backend.cmd: FHD_ROOT=%FHD_ROOT%
echo [INFO] xcagi-backend.cmd: XCAGI_MODS_ROOT=%XCAGI_MODS_ROOT%
echo [INFO] =================================================================

REM 默认监听所有接口，便于本机 127.0.0.1 与局域网 IP 访问同一端口；仅内网调试可设 UVICORN_HOST=127.0.0.1
if not defined UVICORN_HOST set "UVICORN_HOST=0.0.0.0"
REM 浏览器从 192.168.* 等 Origin 直连 API 时须匹配 CORS（与 api/core credentials 一致）
if not defined XCAGI_DEV_ALLOW_LAN_CORS set "XCAGI_DEV_ALLOW_LAN_CORS=1"

REM If no extension mods are loaded, some business list APIs may be empty.
REM For pure library debugging you can set FHD_BUSINESS_DATA_REQUIRES_EXTENSION_MOD=0.
if not defined FHD_BUSINESS_DATA_REQUIRES_EXTENSION_MOD (
  set "FHD_BUSINESS_DATA_REQUIRES_EXTENSION_MOD=1"
)

if exist "%FHD_ROOT%\scripts\fhd-set-database-url.cmd" (
  call "%FHD_ROOT%\scripts\fhd-set-database-url.cmd"
)

REM Prefer XCAGI/.env DATABASE_URL when shell env is not preset.
if not defined DATABASE_URL if exist "%XCAGI_ROOT%\.env" (
  for /f "usebackq tokens=1* delims==" %%A in (`findstr /R /C:"^[ ]*DATABASE_URL[ ]*=" "%XCAGI_ROOT%\.env"`) do (
    set "DATABASE_URL=%%B"
  )
)
if not defined VECTOR_DB_URL if exist "%XCAGI_ROOT%\.env" (
  for /f "usebackq tokens=1* delims==" %%A in (`findstr /R /C:"^[ ]*VECTOR_DB_URL[ ]*=" "%XCAGI_ROOT%\.env"`) do (
    set "VECTOR_DB_URL=%%B"
  )
)

set "PG_PORT="
set "PG5433_UP=0"
set "PG5432_UP=0"
powershell -NoProfile -Command "$c=New-Object Net.Sockets.TcpClient; try{$c.Connect('127.0.0.1',5433); exit 0} catch {exit 1} finally{$c.Dispose()}" >nul 2>&1
if not errorlevel 1 set "PG5433_UP=1"
powershell -NoProfile -Command "$c=New-Object Net.Sockets.TcpClient; try{$c.Connect('127.0.0.1',5432); exit 0} catch {exit 1} finally{$c.Dispose()}" >nul 2>&1
if not errorlevel 1 set "PG5432_UP=1"

if defined DATABASE_URL (
  if "!PG5433_UP!"=="0" if "!PG5432_UP!"=="1" (
    set "DATABASE_URL=!DATABASE_URL:127.0.0.1:5433=127.0.0.1:5432!"
    set "DATABASE_URL=!DATABASE_URL:localhost:5433=localhost:5432!"
    echo [INFO] DATABASE_URL auto-fixed from 5433 to 5432 based on live port detection.
  )
)
if not defined DATABASE_URL (
  if "!PG5433_UP!"=="1" (
    set "PG_PORT=5433"
    echo [INFO] Auto-detected local PostgreSQL port: !PG_PORT!
  ) else if "!PG5432_UP!"=="1" (
    set "PG_PORT=5432"
    echo [INFO] Auto-detected local PostgreSQL port: !PG_PORT!
  ) else (
    set "PG_PORT=5433"
    echo [WARN] PostgreSQL not detected on 127.0.0.1:5433/5432, fallback to !PG_PORT!.
  )
  set "DATABASE_URL=postgresql+psycopg://xcagi:xcagi@127.0.0.1:!PG_PORT!/xcagi"
)
if not defined FHD_TEST_DATABASE_URL call :derive_fhd_test_db
if defined FHD_TEST_DATABASE_URL (
  if "!PG5433_UP!"=="0" if "!PG5432_UP!"=="1" (
    set "FHD_TEST_DATABASE_URL=!FHD_TEST_DATABASE_URL:127.0.0.1:5433=127.0.0.1:5432!"
    set "FHD_TEST_DATABASE_URL=!FHD_TEST_DATABASE_URL:localhost:5433=localhost:5432!"
  )
)

if exist "%XCAGI_ROOT%\.venv\Scripts\python.exe" (
  set "PY_EXE=%XCAGI_ROOT%\.venv\Scripts\python.exe"
) else if exist "%FHD_ROOT%\.venv\Scripts\python.exe" (
  set "PY_EXE=%FHD_ROOT%\.venv\Scripts\python.exe"
) else (
  set "PY_EXE=python"
)

set "PYTHONUTF8=1"

echo [INFO] Python: %PY_EXE%
echo [INFO] DATABASE_URL=%DATABASE_URL%

REM ---------------------------------------------------------------------------
REM API stack mode (Updated 2026-04-17):
REM   default = FHD app.fastapi_app:get_fastapi_app (unified FastAPI entry, port 5000)
REM   NOTE: compact/FHD stack removed - backend.http_app deleted in migration
REM ---------------------------------------------------------------------------
REM Health endpoint: http://127.0.0.1:5000/api/health
REM API docs: http://127.0.0.1:5000/docs
REM ---------------------------------------------------------------------------
goto :run_stack_select

:derive_fhd_test_db
set "FHD_TEST_DATABASE_URL=!DATABASE_URL!"
echo "!DATABASE_URL!" | findstr /i /r "^postgresql" >nul
if errorlevel 1 goto :derive_fhd_sqlite_8k
for /f "usebackq delims=" %%U in (`powershell -NoProfile -Command "$u=$env:DATABASE_URL; $u -creplace '/xcagi$','/xcagi_test'"`) do set "FHD_TEST_DATABASE_URL=%%U"
exit /b 0
:derive_fhd_sqlite_8k
echo "!DATABASE_URL!" | findstr /i /r "^sqlite" >nul
if errorlevel 1 exit /b 0
set "FHD_TEST_DATABASE_URL=!DATABASE_URL:products.db=products_test.db!"
exit /b 0

:run_stack_select
REM Stack selection: only full stack available (compact removed)
goto :stack_full

:stack_full
cd /d "%FHD_ROOT%"
set "PYTHONPATH=%FHD_ROOT%"
echo [INFO] API stack: XCAGI unified FastAPI (app.fastapi_app:get_fastapi_app)
echo [INFO] Starting FastAPI bind=!UVICORN_HOST! port=5000 ^(browse http://127.0.0.1:5000/docs^)
echo [INFO] API docs: http://127.0.0.1:5000/docs
echo [INFO] Health: http://127.0.0.1:5000/api/health
echo [INFO] =================================================================

REM --reload-dir：只监视业务代码目录，避免改动 XCAGI\*.py / 文档时误触发全量重载打断请求
REM --factory：get_fastapi_app 为应用工厂，与 uvicorn 推荐用法一致
"%PY_EXE%" -m uvicorn app.fastapi_app:get_fastapi_app --factory --host !UVICORN_HOST! --port 5000 --reload --reload-dir "%FHD_ROOT%\app" --reload-dir "%FHD_ROOT%\backend" --reload-dir "%FHD_ROOT%\mods" --reload-dir "%FHD_ROOT%\resources"
set "FULL_RC=%ERRORLEVEL%"
REM Windows: Ctrl+C / console close often yields 3221225786 ^(0xC000013A^) — not a startup failure.
if "%FULL_RC%"=="3221225786" (
  echo [INFO] Server stopped ^(Ctrl+C or window close^).
  exit /b 0
)
if not "%FULL_RC%"=="0" (
  echo [ERROR] Server exited with code %FULL_RC%. Scroll up for Python traceback.
  echo [HINT] Check that all dependencies are installed: pip install -r requirements.txt
  pause
  exit /b %FULL_RC%
)
REM [stack_compact removed 2026-04-17] unified entry: FHD app.fastapi_app:get_fastapi_app
exit /b 0
