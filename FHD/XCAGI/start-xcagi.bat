@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
title XCAGI v5.0 - Unified FastAPI Entry

echo =============================================
echo   XCAGI Startup Script v5.1
echo   UPDATED: 2026-04-19 - Startup Fixes
echo =============================================
echo.
echo [INFO] Web/PostgreSQL 开发：继续用本脚本。
echo [INFO] 桌面交付验收（SQLite 本地库，所有 SKU）：请用 start-desktop-sqlite.bat
echo.
echo [INFO] This window is the launcher only (ASCII help avoids CMD UTF-8 parse bugs).
echo [INFO] CHANGELOG 2026-04-19:
echo [INFO]   - Fixed: node_modules path (removed stray \r)
echo [INFO]   - Fixed: Docker executable path (resources not \r\nesources)
echo [INFO]   - Fixed: Backend window inherits DATABASE_URL / VECTOR_DB_URL
echo [INFO]   - Fixed: Backend launcher renamed to xcagi-backend.cmd (port 5000)
echo [INFO]   - Fixed: Build output path to XCAGI\templates\vue-dist
echo [INFO] CHANGELOG 2026-04-17:
echo [INFO]   - Backend unified to port 5000 (FastAPI)
echo [INFO]   - Deleted: backend.http_app (port 8000) - migrated to XCAGI
echo [INFO]   - Deleted: app/routes/ (Flask) - migrated to XCAGI FastAPI
echo [INFO]   - Now uses: uvicorn app.fastapi_app:get_fastapi_app --port 5000
echo [INFO] Other windows: "XCAGI Backend" port 5000, "XCAGI Frontend" port 5001.
echo [INFO] Closing this launcher does NOT stop Backend or Frontend. Ctrl+C in those windows to stop.
echo [INFO] DB: DATABASE_URL from XCAGI/.env if not already set in this CMD; may rewrite :5433 to :5432; if still unset, defaults apply ^(see line after [5/5]^).
echo [INFO] Skip prod build: set XCAGI_FRONTEND_BUILD=0
echo [INFO] MODstore ^(API 8765 + UI 5174^): OFF by default ^(saves CPU/RAM^). Set XCAGI_START_MODSTORE=1 to enable.
echo.

cd /d "%~dp0"
set "XCAGI_DIR=%CD%"
if "%XCAGI_DIR:~-1%"=="\" set "XCAGI_DIR=%XCAGI_DIR:~0,-1%"

echo.
echo [LAUNCHER DEBUG] Bat location: %~f0
echo [LAUNCHER DEBUG] Working directory: %CD%
echo [LAUNCHER DEBUG] If this window flashes and closes unexpectedly, edit the desktop shortcut:
echo [LAUNCHER DEBUG]   Target -> cmd.exe /k "E:\FHD\XCAGI\start-xcagi.bat"
echo [LAUNCHER DEBUG]   Start in -> E:\FHD\XCAGI
echo.

REM %~dp0 always ends with \ - use %%CD%% after cd /d for a stable absolute path (CRLF line endings required for .bat on Windows).
REM Default to force frontend build every run (1=build, 0=skip).
if not defined XCAGI_FRONTEND_BUILD set "XCAGI_FRONTEND_BUILD=1"

pushd "%XCAGI_DIR%\.."
set "FHD_ROOT=%CD%"
popd
set "FRONTEND_DIR=%FHD_ROOT%\frontend"

if exist "%FHD_ROOT%\.venv\Scripts\python.exe" (
    set "PY_EXE=%FHD_ROOT%\.venv\Scripts\python.exe"
) else if exist "%XCAGI_DIR%\.venv\Scripts\python.exe" (
    set "PY_EXE=%XCAGI_DIR%\.venv\Scripts\python.exe"
) else (
    set "PY_EXE=python"
)

echo [1/5] Checking Python...
"%PY_EXE%" --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found or unusable: %PY_EXE%
    call :fail
)
echo [INFO] Python: %PY_EXE%

echo [2/5] Checking frontend dependencies...
if not exist "%FRONTEND_DIR%\node_modules" (
    echo [INFO] Installing frontend dependencies...
    pushd "%FRONTEND_DIR%"
    cmd /c "npm install"
    if errorlevel 1 (
        echo [ERROR] npm install failed.
        popd
        call :fail
    )
    popd
)

if defined XCAGI_SKIP_FRONTEND_BUILD (
    echo [INFO] XCAGI_SKIP_FRONTEND_BUILD is set - skipping npm run build.
    goto :after_fe_build
)
if /I "%XCAGI_FRONTEND_BUILD%"=="0" (
    echo [INFO] XCAGI_FRONTEND_BUILD=0 - skipping npm run build.
    goto :after_fe_build
)
if /I not "%XCAGI_FRONTEND_BUILD%"=="1" (
    echo [WARN] Unknown XCAGI_FRONTEND_BUILD=%XCAGI_FRONTEND_BUILD%; treating as 1.
)
REM [3/5] Production build runs in its own window; /WAIT continues here only after npm exits. Avoids ERRORLEVEL mis-capture after call.
echo [3/5] Frontend production build - opening window "XCAGI Frontend Build" (npm run build)...
start "XCAGI Frontend Build" /WAIT /D "%FRONTEND_DIR%" cmd /c "npm.cmd run build"
if errorlevel 1 (
    echo [ERROR] npm run build failed. See the "XCAGI Frontend Build" window, or set XCAGI_SKIP_FRONTEND_BUILD=1 to skip - dev only.
    call :fail
)
echo [INFO] Build output (Vite): %FHD_ROOT%\templates\vue-dist

:after_fe_build

echo [4/5] Checking data directory...
if not exist "%XCAGI_DIR%\data" (
    mkdir "%XCAGI_DIR%\data"
)

echo [5/5] Database configuration...

REM Load XCAGI/.env before Docker helper so DATABASE_URL is available for compose.
if not defined DATABASE_URL if exist "%XCAGI_DIR%\.env" (
    for /f "usebackq tokens=1* delims==" %%A in (`findstr /R /C:"^[ ]*DATABASE_URL[ ]*=" "%XCAGI_DIR%\.env"`) do (
        set "DATABASE_URL=%%B"
    )
)
if not defined VECTOR_DB_URL if exist "%XCAGI_DIR%\.env" (
    for /f "usebackq tokens=1* delims==" %%A in (`findstr /R /C:"^[ ]*VECTOR_DB_URL[ ]*=" "%XCAGI_DIR%\.env"`) do (
        set "VECTOR_DB_URL=%%B"
    )
)

REM Probe local Postgres ports BEFORE :try_start_postgres so "already listening" skips Docker/SQLite fallback.
set "PG_PORT="
set "PG5433_UP=0"
set "PG5432_UP=0"
powershell -NoProfile -Command "$c=New-Object Net.Sockets.TcpClient; try{$c.Connect('127.0.0.1',5433); exit 0} catch {exit 1} finally{$c.Dispose()}" >nul 2>&1
if not errorlevel 1 set "PG5433_UP=1"
powershell -NoProfile -Command "$c=New-Object Net.Sockets.TcpClient; try{$c.Connect('127.0.0.1',5432); exit 0} catch {exit 1} finally{$c.Dispose()}" >nul 2>&1
if not errorlevel 1 set "PG5432_UP=1"

REM === PostgreSQL helpers / optional SQLite fallback (never overwrites existing DATABASE_URL) ===
call :try_start_postgres
if exist "%FHD_ROOT%\scripts\fhd-set-database-url.cmd" (
    call "%FHD_ROOT%\scripts\fhd-set-database-url.cmd" >nul
)

REM If a helper cleared DATABASE_URL, re-apply .env once.
if not defined DATABASE_URL if exist "%XCAGI_DIR%\.env" (
    for /f "usebackq tokens=1* delims==" %%A in (`findstr /R /C:"^[ ]*DATABASE_URL[ ]*=" "%XCAGI_DIR%\.env"`) do (
        set "DATABASE_URL=%%B"
    )
)

REM FHD backend uses PostgreSQL only
if defined DATABASE_URL (
    if "!PG5433_UP!"=="0" if "!PG5432_UP!"=="1" (
        set "DATABASE_URL=!DATABASE_URL:127.0.0.1:5433=127.0.0.1:5432!"
        set "DATABASE_URL=!DATABASE_URL:localhost:5433=localhost:5432!"
        echo [INFO] DATABASE_URL auto-fixed from 5433 to 5432 based on live port detection.
    )
)
if not defined DATABASE_URL (
    REM Check if PostgreSQL is already running
    if "!PG5433_UP!"=="1" (
        set "PG_PORT=5433"
        echo [INFO] Auto-detected local PostgreSQL port: !PG_PORT!
        set "DATABASE_URL=postgresql+psycopg://xcagi:xcagi@127.0.0.1:!PG_PORT!/xcagi"
    ) else if "!PG5432_UP!"=="1" (
        set "PG_PORT=5432"
        echo [INFO] Auto-detected local PostgreSQL port: !PG_PORT!
        set "DATABASE_URL=postgresql+psycopg://xcagi:xcagi@127.0.0.1:!PG_PORT!/xcagi"
    ) else (
        REM No PostgreSQL running and no DATABASE_URL set - use SQLite
        echo [INFO] No PostgreSQL detected on 127.0.0.1:5433/5432 - using SQLite.
        set "DATABASE_URL=sqlite:///%XCAGI_DIR:\=/%/data/products.db"
    )
)
if not defined FHD_TEST_DATABASE_URL call :derive_fhd_test_db
if defined FHD_TEST_DATABASE_URL (
    if "!PG5433_UP!"=="0" if "!PG5432_UP!"=="1" (
        set "FHD_TEST_DATABASE_URL=!FHD_TEST_DATABASE_URL:127.0.0.1:5433=127.0.0.1:5432!"
        set "FHD_TEST_DATABASE_URL=!FHD_TEST_DATABASE_URL:localhost:5433=localhost:5432!"
    )
)

echo [INFO] DATABASE_URL=%DATABASE_URL%
echo.

echo [INFO] Verifying DATABASE_URL connectivity...

REM Smart verification: skip psycopg test for SQLite
echo %DATABASE_URL% | findstr /I "sqlite" >nul
if not errorlevel 1 (
    echo [INFO] Using SQLite - skipping PostgreSQL connectivity test.
    goto :db_verified
)

REM docker compose up -d returns before Postgres accepts TCP; single-shot connect often fails and hits :fail.
echo [INFO] PostgreSQL: retrying connect up to 30 times ^(~60s^) so container can finish init...
set "PG_TRY=0"
:pg_connect_retry
set /a PG_TRY+=1
"%PY_EXE%" -c "import os,sys,psycopg; url=os.environ.get('DATABASE_URL','').replace('+psycopg',''); conn=psycopg.connect(url, connect_timeout=5); conn.execute('select 1'); conn.close()" >nul 2>&1
if not errorlevel 1 goto :db_verified
if !PG_TRY! GEQ 30 (
    echo [ERROR] Cannot connect to PostgreSQL after 30 attempts.
    echo [HINT] docker logs xcagi-postgres
    call :fail
)
echo [INFO] Waiting for PostgreSQL... !PG_TRY!/30 ^(container may still be starting^)
ping 127.0.0.1 -n 3 >nul
goto :pg_connect_retry

:db_verified

REM === MODstore: API :8765 + Vite :5174（可选；默认不启以降低本机压力）===
set "MODSTORE_STARTED=0"
if /I not "%XCAGI_START_MODSTORE%"=="1" (
    if /I "%XCAGI_START_MODSTORE%"=="0" (
        echo [INFO] XCAGI_START_MODSTORE=0 - skipping MODstore.
    ) else (
        echo [INFO] MODstore skipped ^(default^). Set XCAGI_START_MODSTORE=1 to start MODstore API + UI.
    )
    goto :after_modstore_launch
)
if exist "%FHD_ROOT%\MODstore\start-modstore.bat" (
    if not defined XCAGI_MOD_CATALOG_URL (
        set "XCAGI_MOD_CATALOG_URL=http://127.0.0.1:8765"
        echo [MODstore] XCAGI_MOD_CATALOG_URL not set - defaulting to !XCAGI_MOD_CATALOG_URL! ^(merge /api/mod-store/catalog^)
    ) else (
        echo [MODstore] XCAGI_MOD_CATALOG_URL already set: !XCAGI_MOD_CATALOG_URL!
    )
    echo [MODstore] Starting ^(see windows "MODstore API" / "MODstore UI"^)...
    start "MODstore" /D "%FHD_ROOT%\MODstore" cmd /c "call start-modstore.bat"
    ping 127.0.0.1 -n 3 >nul
    set "MODSTORE_STARTED=1"
) else (
    echo [INFO] MODstore not found ^(%FHD_ROOT%\MODstore\start-modstore.bat^) - skipped.
)
:after_modstore_launch

echo Starting services...
echo.

set PYTHONUTF8=1

REM Ensure mods root is set before starting backend (inherited by child processes)
if not defined XCAGI_MODS_ROOT (
    set "XCAGI_MODS_ROOT=%FHD_ROOT%\mods"
    echo [INFO] XCAGI_MODS_ROOT set to: %XCAGI_MODS_ROOT%
)

REM If 5000 is already serving this app, do not start a second Backend window (avoids WinError 10048 bind).
set "BACKEND_READY=0"
if not defined XCAGI_FORCE_BACKEND_RESTART (
    powershell -NoProfile -Command "try { $r=Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:5000/api/health' -TimeoutSec 2; if($r.StatusCode -eq 200){ exit 0 } else { exit 1 } } catch { exit 1 }" >nul 2>&1
    if not errorlevel 1 (
        echo [INFO] Port 5000 already responds to /api/health - skipping a second "XCAGI Backend" window.
        echo [INFO] To restart: close the old Backend window, or: taskkill /FI "WINDOWTITLE eq XCAGI Backend*" /F
        echo [INFO] Or set XCAGI_FORCE_BACKEND_RESTART=1 before this script to start anyway ^(will error if port still in use^).
        set "BACKEND_READY=1"
        goto :backend_ready
    )
)

echo [Backend] Starting FastAPI on port 5000 (Unified Entry)...
echo [INFO] Stack: XCAGI unified FastAPI (app.fastapi_app:get_fastapi_app)

REM Check if backend launcher exists
if not exist "%XCAGI_DIR%\xcagi-backend.cmd" (
    echo [ERROR] Backend launcher not found: %XCAGI_DIR%\xcagi-backend.cmd
    call :fail
)

REM Start backend in a new window - environment variables are inherited automatically
start "XCAGI Backend" /D "%XCAGI_DIR%" cmd /k "call xcagi-backend.cmd"
set "BACKEND_READY=0"
REM Cold start (DB migrate, first import) can exceed ~1min; short waits caused "Failed to fetch" storms in the UI.
for /L %%I in (1,1,55) do (
    powershell -NoProfile -Command "try { $r=Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:5000/api/health' -TimeoutSec 2; if($r.StatusCode -eq 200){ exit 0 } else { exit 1 } } catch { exit 1 }" >nul 2>&1
    if not errorlevel 1 (
        set "BACKEND_READY=1"
        goto :backend_ready
    )
    if %%I==1 echo [INFO] Waiting for backend health endpoint /api/health on port 5000...
    ping 127.0.0.1 -n 2 >nul
)
:backend_ready
if "!BACKEND_READY!"=="1" (
    echo [INFO] Backend is ready on http://127.0.0.1:5000
    echo [INFO] API docs: http://127.0.0.1:5000/docs
) else (
    echo [WARN] Backend health check timed out; starting frontend anyway.
)

echo [Frontend] Starting Vite on port 5001...
if not exist "%FRONTEND_DIR%\node_modules\.bin\vite.cmd" (
    echo [WARN] vite not found - running npm install first...
    pushd "%FRONTEND_DIR%"
    call npm.cmd install
    popd
)
start "XCAGI Frontend" /D "%FRONTEND_DIR%" cmd /k "npm.cmd run dev"
ping 127.0.0.1 -n 5 >nul

REM Backend may become healthy while Vite starts; avoid opening the browser before API is up.
if "!BACKEND_READY!"=="0" (
    echo [INFO] Backend not healthy yet - extra wait before browser ^(reduce "Failed to fetch" on first load^)...
    for /L %%J in (1,1,25) do (
        powershell -NoProfile -Command "try { $r=Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:5000/api/health' -TimeoutSec 3; if($r.StatusCode -eq 200){ exit 0 } else { exit 1 } } catch { exit 1 }" >nul 2>&1
        if not errorlevel 1 (
            set "BACKEND_READY=1"
            echo [INFO] Backend is ready on http://127.0.0.1:5000
            goto :after_backend_grace
        )
        if %%J==1 echo [INFO] Still waiting for /api/health ^(up to ~75s^) - check "XCAGI Backend" window for errors...
        ping 127.0.0.1 -n 3 >nul
    )
    echo [WARN] Backend still not healthy. Open http://127.0.0.1:5000/docs in a tab; fix errors in "XCAGI Backend", then refresh http://127.0.0.1:5001/
)
:after_backend_grace

echo.
REM Open browser (non-empty START title avoids edge-case "syntax incorrect" with some locales/paths)
start "XCAGI Browser" "http://127.0.0.1:5001/"

echo.
echo =============================================
echo   XCAGI Startup Summary (Unified Entry)
echo =============================================
echo   [1] Backend:  http://127.0.0.1:5000  API docs: http://127.0.0.1:5000/docs
echo   [2] Frontend: http://127.0.0.1:5001
echo   [3] Production build output: %FHD_ROOT%\templates\vue-dist
if "!MODSTORE_STARTED!"=="1" (
    echo   [4] MODstore UI:  http://127.0.0.1:5174  ^(嵌入 XCAGI「MOD 扩展」页默认地址^)
    echo   [5] MODstore API: http://127.0.0.1:8765/docs  Catalog: /v1/index.json
)
echo   Database: see DATABASE_URL line above or Backend window.
echo.
echo   Migration Notice (2026-04-17):
echo     - Port 8000 backend deleted (backend.http_app removed)
echo     - Port 5000 is now the unified FastAPI entry
echo     - All Flask routes migrated to XCAGI FastAPI
echo.
echo   Optional env - set in the same CMD before running this script:
echo     XCAGI_FRONTEND_BUILD=0
echo     XCAGI_SKIP_FRONTEND_BUILD=1
echo     XCAGI_NO_PAUSE=1
echo     XCAGI_FORCE_BACKEND_RESTART=1   start Backend even if 5000 already has a healthy API
echo     XCAGI_START_MODSTORE=1           spawn MODstore ^(API 8765 + UI 5174^); default is OFF
echo     XCAGI_MOD_CATALOG_URL=...        override catalog base ^(default http://127.0.0.1:8765 when MODstore starts^)
echo     XCAGI_NEURO_INTENT=0            disable NeuroBus + reflex/unified intent bridge ^(default on^)
echo =============================================
echo [INFO] If 5001 is blank: check Backend window and http://127.0.0.1:5000/api/health
echo.
echo [IMPORTANT] This launcher window will ALWAYS pause at the end so you can read any errors.
echo [HINT] The services (Backend on 5000 + Frontend on 5001) continue running even after you close this window.
echo [HINT] If the window still flashes and disappears immediately, edit the desktop shortcut:
echo          Right-click shortcut ^> Properties ^> Target:
echo             cmd.exe /k "E:\FHD\XCAGI\start-xcagi.bat"
echo          Start in:
echo             E:\FHD\XCAGI
echo.
echo [INFO] Press any key to close THIS launcher only. Backend + Frontend keep running in their own windows.
pause
goto :eof

:fail
echo.
echo Press any key to close this window...
pause
exit /b 1

:derive_fhd_test_db
set "FHD_TEST_DATABASE_URL=!DATABASE_URL!"
echo "!DATABASE_URL!" | findstr /i /r "^postgresql" >nul
if errorlevel 1 goto :derive_fhd_sqlite_bat
for /f "usebackq delims=" %%U in (`powershell -NoProfile -Command "$u=$env:DATABASE_URL; $u -creplace '/xcagi$','/xcagi_test'"`) do set "FHD_TEST_DATABASE_URL=%%U"
exit /b 0
:derive_fhd_sqlite_bat
echo "!DATABASE_URL!" | findstr /i /r "^sqlite" >nul
if errorlevel 1 exit /b 0
set "FHD_TEST_DATABASE_URL=!DATABASE_URL:products.db=products_test.db!"
exit /b 0

:try_start_postgres
    REM Check if PostgreSQL is already running
    if "!PG5433_UP!"=="1" (
        echo [INFO] PostgreSQL already running on port 5433 - skip container start.
        goto :eof
    )
    if "!PG5432_UP!"=="1" (
        echo [INFO] PostgreSQL already running on port 5432 - skip container start.
        goto :eof
    )

    REM Auto-detect Docker availability (check if daemon is responsive)
    set "DOCKER_AVAILABLE=0"
    set "DOCKER_EXE="
    for %%D in (
        "C:\Program Files\Docker\Docker\resources\bin\docker.exe"
        "C:\Program Files (x86)\Docker\Docker\resources\bin\docker.exe"
        "C:\Program Files\Docker\resources\bin\docker.exe"
    ) do (
        if exist %%~D (
            set "DOCKER_EXE=%%~D"
        )
    )

    REM Test if Docker daemon is actually running
    if defined DOCKER_EXE (
        "!DOCKER_EXE!" info >nul 2>&1
        if not errorlevel 1 (
            set "DOCKER_AVAILABLE=1"
        ) else (
            echo [WARN] Docker found but daemon is not running.
        )
    )

    REM If Docker is not available, fallback to SQLite immediately
    if "!DOCKER_AVAILABLE!"=="0" (
        echo [INFO] Docker not available - using SQLite database instead.
        if not defined DATABASE_URL (
            set "DATABASE_URL=sqlite:///%XCAGI_DIR:\=/%/data/products.db"
            echo [INFO] Set DATABASE_URL=!DATABASE_URL!
        )
        goto :eof
    )

    REM Try legacy helper first
    if exist "%FHD_ROOT%\scripts\docker-postgres-for-fhd.bat" (
        echo [INFO] Starting PostgreSQL using legacy helper...
        call "%FHD_ROOT%\scripts\docker-postgres-for-fhd.bat" >nul 2>&1
        if not errorlevel 1 (
            echo [INFO] PostgreSQL container started via legacy helper.
            goto :eof
        ) else (
            echo [WARN] Legacy helper failed - will try docker compose directly.
        )
    )

    REM Start postgres container with docker compose
    if defined DOCKER_EXE (
        echo [INFO] Found Docker at: !DOCKER_EXE!
        pushd "%XCAGI_DIR%"
        echo [INFO] Starting postgres container...
        "!DOCKER_EXE!" compose up -d postgres >nul 2>&1
        set "DOCKER_UP=!ERRORLEVEL!"
        popd
        if "!DOCKER_UP!"=="0" (
            echo [INFO] Postgres container started; it may take several seconds before port 5432 accepts connections.
        ) else (
            echo [WARN] docker compose failed (code !DOCKER_UP!) - falling back to SQLite.
            if not defined DATABASE_URL (
                set "DATABASE_URL=sqlite:///%XCAGI_DIR:\=/%/data/products.db"
                echo [INFO] Set DATABASE_URL=!DATABASE_URL!
            )
        )
    )
    goto :eof

