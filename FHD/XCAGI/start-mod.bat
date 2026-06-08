@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion

rem ============================================
rem XCAGI Mod startup (load mod blueprints)
rem ============================================

cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "XCAGI_PHONE_LOOPBACK=0"
set "XCAGI_PHONE_USE_DEFAULT_MIC=1"

echo.
echo ========================================
echo XCAGI Mod Startup (blueprints enabled)
echo ========================================
echo.

rem 1) Resolve Python executable
set "PYTHON_EXE="
if exist "%~dp0.venv\Scripts\python.exe" (
    for %%I in ("%~dp0.venv\Scripts\python.exe") do set "PYTHON_EXE=%%~fI"
)
if not defined PYTHON_EXE if exist "%~dp0..\.venv\Scripts\python.exe" (
    for %%I in ("%~dp0..\.venv\Scripts\python.exe") do set "PYTHON_EXE=%%~fI"
)
if not defined PYTHON_EXE set "PYTHON_EXE=python"

rem 1.1) Check 8000 port conflict and kill if exists (FastAPI backend)
for /f "tokens=5" %%p in ('netstat -ano ^| findstr /r /c:":8000 .*LISTENING"') do (
    echo [INFO] Port 8000 is in use by PID %%p, terminating...
    taskkill /PID %%p /F >nul 2>&1
    ping 127.0.0.1 -n 2 >nul
)

rem 1.1b) Check 5001 port conflict and kill if exists (frontend)
for /f "tokens=5" %%p in ('netstat -ano ^| findstr /r /c:":5001 .*LISTENING"') do (
    echo [INFO] Port 5001 is in use by PID %%p, terminating...
    taskkill /PID %%p /F >nul 2>&1
    ping 127.0.0.1 -n 2 >nul
)

rem 1.2) adb preflight for real_phone workflow
set "ADB_EXE="
set "ADB_ONLINE="
for /f "delims=" %%i in ('where adb 2^>nul') do (
    set "ADB_EXE=%%i"
    goto :AdbChecked
)
:AdbChecked
if not defined ADB_EXE (
    echo [WARN] adb not found in PATH. real_phone workflow may not work.
) else (
    echo [INFO] adb: !ADB_EXE!
    for /f "delims=" %%d in ('adb devices 2^>nul ^| findstr /r /c:"device$"') do (
        set "ADB_ONLINE=1"
    )
    if not defined ADB_ONLINE (
        echo [WARN] No online Android device. Enable USB/Wireless debugging.
    ) else (
        echo [OK] Android device detected.
    )
)

echo [1/2] Starting FastAPI backend at http://127.0.0.1:8000 (WITH MODS) ...
echo        Python : %PYTHON_EXE%
if /I "%PYTHON_EXE%"=="python" (
    start "XCAGI FastAPI Backend (Mod)" /D "%~dp0" cmd /k python run_fastapi.py
) else (
    rem PYTHON_EXE is typically a short path under .venv (no spaces).
    start "XCAGI FastAPI Backend (Mod)" /D "%~dp0" cmd /k %PYTHON_EXE% run_fastapi.py
)

rem 2) Start frontend Vite on port 5001
set "NPM_CMD="
set "FRONTEND_SHIM=%~dp0frontend\r\npm.cmd"

:: ---------- Resolve npm.cmd from machine/user environment (no hardcoded drive paths) ----------
:: 必须用 goto，不能用 call：后面会 goto :NpmFound 并一路执行到 exit /b 0；
:: 若用 call，exit /b 只会返回到此处，接着会清空 NPM_CMD 并重复启动前端（甚至死循环）。
goto :FindNpm

:FindNpm
set "NPM_CMD="
:: 1) First hit from where.exe on merged PATH (skips this repo's frontend\r\npm.cmd shim)
for /f "delims=" %%i in ('where npm.cmd 2^>nul') do (
    if /i not "%%~fi"=="%FRONTEND_SHIM%" (
        set "NPM_CMD=%%~fi"
        goto :NpmFound
    )
)
:: 2) Common env vars (nvm-windows, Volta, manual installs, fnm)
if defined NVM_SYMLINK if exist "!NVM_SYMLINK!\r\npm.cmd" (
    set "NPM_CMD=!NVM_SYMLINK!\r\npm.cmd"
    goto :NpmFound
)
if defined NODE_HOME if exist "!NODE_HOME!\r\npm.cmd" (
    set "NPM_CMD=!NODE_HOME!\r\npm.cmd"
    goto :NpmFound
)
if defined NODE_HOME if exist "!NODE_HOME!\bin\r\npm.cmd" (
    set "NPM_CMD=!NODE_HOME!\bin\r\npm.cmd"
    goto :NpmFound
)
if defined VOLTA_HOME if exist "!VOLTA_HOME!\bin\r\npm.cmd" (
    set "NPM_CMD=!VOLTA_HOME!\bin\r\npm.cmd"
    goto :NpmFound
)
if defined FNM_MULTISHELL_PATH if exist "!FNM_MULTISHELL_PATH!\r\npm.cmd" (
    set "NPM_CMD=!FNM_MULTISHELL_PATH!\r\npm.cmd"
    goto :NpmFound
)
if defined FNM_DIR (
    if exist "!FNM_DIR!\aliases\default\r\npm.cmd" (
        set "NPM_CMD=!FNM_DIR!\aliases\default\r\npm.cmd"
        goto :NpmFound
    )
    if exist "!FNM_DIR!\r\npm.cmd" (
        set "NPM_CMD=!FNM_DIR!\r\npm.cmd"
        goto :NpmFound
    )
)
if defined NODIST_PREFIX if exist "!NODIST_PREFIX!\r\npm.cmd" (
    set "NPM_CMD=!NODIST_PREFIX!\r\npm.cmd"
    goto :NpmFound
)
:: 3) Walk PATH segments for npm.cmd (covers Scoop/shims, custom dirs if where failed)
set "_PW=!PATH!"
:FindNpmWalk
if not defined _PW goto FindNpmFallback
set "_PREV=!_PW!"
for /f "tokens=1* delims=;" %%a in ("!_PW!") do (
    set "_SEG=%%~a"
    set "_PW=%%b"
)
if "!_PREV!"=="!_PW!" goto FindNpmFallback
if defined _SEG if exist "!_SEG!\r\npm.cmd" (
    if /i not "!_SEG!\r\npm.cmd"=="%FRONTEND_SHIM%" (
        set "NPM_CMD=!_SEG!\r\npm.cmd"
        goto :NpmFound
    )
)
goto FindNpmWalk

:: 4) Last resort: repo shim delegates to real npm; then default installer paths
:FindNpmFallback
if exist "%FRONTEND_SHIM%" (
    set "NPM_CMD=%FRONTEND_SHIM%"
    goto :NpmFound
)
if exist "%ProgramFiles%\r\nodejs\r\npm.cmd" (
    set "NPM_CMD=%ProgramFiles%\r\nodejs\r\npm.cmd"
    goto :NpmFound
)
if exist "%ProgramFiles(x86)%\r\nodejs\r\npm.cmd" (
    set "NPM_CMD=%ProgramFiles(x86)%\r\nodejs\r\npm.cmd"
    goto :NpmFound
)

:NpmFound
if not defined NPM_CMD (
    echo [ERROR] npm.cmd not found in environment.
    echo Ensure Node.js is installed and PATH or NVM_SYMLINK / NODE_HOME / VOLTA_HOME / FNM_DIR points to it.
    echo Then: cd frontend ^&^& npm install
    pause
    exit /b 1
)
if not exist "%~dp0frontend\package.json" (
    echo [ERROR] frontend\package.json not found.
    pause
    exit /b 1
)

echo [2/2] Starting frontend at http://127.0.0.1:5001 ...
echo        Npm    : %NPM_CMD%
rem Avoid nested quoting; this should reliably pass `run dev` to npm.cmd.
start "XCAGI Frontend" /D "%~dp0frontend" cmd /k %NPM_CMD% run dev

rem 3) Health checks for 8000/5001 with retries
set "BACKEND_OK="
set "FRONTEND_OK="
set /a RETRY_MAX=20
set /a RETRY_I=0
:HealthRetry
set /a RETRY_I+=1
if !RETRY_I! gtr !RETRY_MAX! goto HealthDone

for /f "tokens=5" %%p in ('netstat -ano ^| findstr /r /c:":8000 .*LISTENING"') do (
    set "BACKEND_OK=1"
)
for /f "tokens=5" %%p in ('netstat -ano ^| findstr /r /c:":5001 .*LISTENING"') do (
    set "FRONTEND_OK=1"
)
if defined BACKEND_OK if defined FRONTEND_OK goto HealthDone
ping 127.0.0.1 -n 2 >nul
goto HealthRetry

:HealthDone
echo.
if defined BACKEND_OK (
    echo [PASS] FastAPI backend port 8000 is listening.
) else (
    echo [FAIL] FastAPI backend port 8000 is NOT listening.
)
if defined FRONTEND_OK (
    echo [PASS] Frontend port 5001 is listening.
) else (
    echo [FAIL] Frontend port 5001 is NOT listening.
)
echo.

rem Fail fast if either side didn't come up.
if not defined BACKEND_OK exit /b 1
if not defined FRONTEND_OK exit /b 1

rem Open browser when frontend is up
if defined FRONTEND_OK (
    start "" "http://127.0.0.1:5001/index.html"
) else (
    echo [WARN] Frontend not ready, browser not opened automatically.
)

rem Keep brief pause behavior for readability
ping 127.0.0.1 -n 2 >nul

echo.
echo [OK] FastAPI backend and frontend started.
echo Frontend: http://127.0.0.1:5001/index.html
echo FastAPI Backend : http://127.0.0.1:8000
echo FastAPI Docs    : http://127.0.0.1:8000/docs
echo Mode    : FastAPI with Mod (blueprints enabled)
echo Phone   : real_phone uses ADB status/answer pipeline
echo.
echo Available mods:
echo   - sz-qsm-pro
echo   - example-mod
echo.
echo To stop services, close both backend/frontend windows.
echo.
exit /b 0
