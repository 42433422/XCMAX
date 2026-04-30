@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo.
echo ========================================
echo FHD: XCAGI backend 5000 + Vite frontend 5001
echo ========================================
echo.

echo [1/2] Starting backend at http://127.0.0.1:5000 ^(Unified FastAPI entry^) ...
start "XCAGI Backend" /D "%~dp0XCAGI" cmd /k "call ""%~dp0XCAGI\xcagi-backend-with-db.cmd"""

set "FRONTEND_DIR=%~dp0frontend"
if not exist "%FRONTEND_DIR%\package.json" (
  if exist "%~dp0XCAGI\frontend\package.json" (
    set "FRONTEND_DIR=%~dp0XCAGI\frontend"
  )
)
if not exist "%FRONTEND_DIR%\package.json" (
  echo [WARN] frontend\package.json not found ^(tried repo\frontend and XCAGI\frontend^), skip frontend.
  goto done
)

echo [2/2] Starting frontend at http://127.0.0.1:5001 ...
start "XCAGI Frontend" /D "%FRONTEND_DIR%" cmd /k "npm run dev"

timeout /t 3 /nobreak >nul
start "" "http://127.0.0.1:5001/index.html"

:done
echo.
echo [OK] Startup command executed.
echo Backend : http://127.0.0.1:5000
echo API Docs: http://127.0.0.1:5000/docs
echo Frontend: http://127.0.0.1:5001/index.html
echo.
echo [INFO] Closing this launcher does NOT stop Backend or Frontend
echo.
exit /b 0
