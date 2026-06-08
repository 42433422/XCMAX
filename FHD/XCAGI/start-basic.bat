@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion

:: ============================================
:: XCAGI 基本版启动 (不加载扩展蓝图)
:: ============================================

cd /d "%~dp0"
set "FRONTEND_SHIM=%~dp0frontend\r\npm.cmd"

echo.
echo ========================================
echo XCAGI 基本版启动 (无扩展蓝图)
echo ========================================
echo.

:: 1) Resolve Python executable
set "PYTHON_EXE="
if exist "%~dp0.venv\Scripts\python.exe" set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
if not defined PYTHON_EXE if exist "%~dp0..\.venv\Scripts\python.exe" set "PYTHON_EXE=%~dp0..\.venv\Scripts\python.exe"
if not defined PYTHON_EXE set "PYTHON_EXE=python"

echo [1/2] Starting backend at http://127.0.0.1:5000 (Unified FastAPI entry) ...
echo [INFO] Migrated 2026-04-17: Port 8000 deleted, now using unified port 5000
start "XCAGI Backend (Basic)" /D "%~dp0" cmd /k "call ""%~dp0xcagi-backend.cmd"""

:: 2) Start frontend Vite on port 5001
call :FindNpm
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
echo        Using npm: !NPM_CMD!
start "XCAGI Frontend" /D "%~dp0frontend" cmd /k "call ""!NPM_CMD!"" run dev"

:: Wait briefly before opening browser
timeout /t 3 /nobreak >nul
start "" "http://127.0.0.1:5001/index.html"

echo.
echo [OK] Backend and frontend started.
echo Frontend: http://127.0.0.1:5001/index.html
echo Backend : http://127.0.0.1:8000
echo Mode    : Basic (XCAGI_API_STACK=compact)
echo.
echo To stop services, close both backend/frontend windows.
echo.
exit /b 0

:: ---------- Resolve npm.cmd from machine/user environment ----------
:FindNpm
set "NPM_CMD="
:: 1) First hit from where.exe on merged PATH (skips this repo's frontend\r\npm.cmd shim)
for /f "delims=" %%i in ('where npm.cmd 2^>nul') do (
    if /i not "%%~fi"=="%FRONTEND_SHIM%" (
        set "NPM_CMD=%%~fi"
        exit /b 0
    )
)
:: 2) Common env vars (nvm-windows, Volta, manual installs, fnm)
if defined NVM_SYMLINK if exist "!NVM_SYMLINK!\r\npm.cmd" (
    set "NPM_CMD=!NVM_SYMLINK!\r\npm.cmd"
    exit /b 0
)
if defined NODE_HOME if exist "!NODE_HOME!\r\npm.cmd" (
    set "NPM_CMD=!NODE_HOME!\r\npm.cmd"
    exit /b 0
)
if defined NODE_HOME if exist "!NODE_HOME!\bin\r\npm.cmd" (
    set "NPM_CMD=!NODE_HOME!\bin\r\npm.cmd"
    exit /b 0
)
if defined VOLTA_HOME if exist "!VOLTA_HOME!\bin\r\npm.cmd" (
    set "NPM_CMD=!VOLTA_HOME!\bin\r\npm.cmd"
    exit /b 0
)
if defined FNM_MULTISHELL_PATH if exist "!FNM_MULTISHELL_PATH!\r\npm.cmd" (
    set "NPM_CMD=!FNM_MULTISHELL_PATH!\r\npm.cmd"
    exit /b 0
)
if defined FNM_DIR (
    if exist "!FNM_DIR!\aliases\default\r\npm.cmd" (
        set "NPM_CMD=!FNM_DIR!\aliases\default\r\npm.cmd"
        exit /b 0
    )
    if exist "!FNM_DIR!\r\npm.cmd" (
        set "NPM_CMD=!FNM_DIR!\r\npm.cmd"
        exit /b 0
    )
)
if defined NODIST_PREFIX if exist "!NODIST_PREFIX!\r\npm.cmd" (
    set "NPM_CMD=!NODIST_PREFIX!\r\npm.cmd"
    exit /b 0
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
        exit /b 0
    )
)
goto FindNpmWalk

:: 4) Last resort: repo shim delegates to real npm; then default installer paths
:FindNpmFallback
if exist "%FRONTEND_SHIM%" (
    set "NPM_CMD=%FRONTEND_SHIM%"
    exit /b 0
)
if exist "%ProgramFiles%\r\nodejs\r\npm.cmd" (
    set "NPM_CMD=%ProgramFiles%\r\nodejs\r\npm.cmd"
    exit /b 0
)
if exist "%ProgramFiles(x86)%\r\nodejs\r\npm.cmd" (
    set "NPM_CMD=%ProgramFiles(x86)%\r\nodejs\r\npm.cmd"
    exit /b 0
)
exit /b 0
