@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
title XCAGI 桌面版（SQLite 本地库 — 所有 SKU）

REM ---------------------------------------------------------------------------
REM  桌面交付基线：后端见 xcagi-backend-desktop.cmd（与 Electron 安装包一致）
REM  数据目录：XCAGI\data\desktop-dev\（安装包默认 %%APPDATA%%\XCAGI）
REM  SKU：默认 enterprise，可通过 XCAGI_PRODUCT_SKU 覆盖
REM ---------------------------------------------------------------------------

cd /d "%~dp0"
set "XCAGI_DIR=%CD%"
pushd "%XCAGI_DIR%\.."
set "FHD_ROOT=%CD%"
popd

if not defined XCAGI_PRODUCT_SKU set "XCAGI_PRODUCT_SKU=enterprise"

echo.
echo ========================================
echo   XCAGI 桌面版 — SQLite 本地库
echo ========================================
echo   SKU:      %XCAGI_PRODUCT_SKU%
echo   数据目录: %XCAGI_DIR%\data\desktop-dev
echo   Web/Postgres 开发: ..\start-xcagi.bat 或 xcagi-backend.cmd
echo ========================================
echo.

powershell -NoProfile -Command "try { $r=Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:5000/api/health' -TimeoutSec 2; if($r.StatusCode -eq 200){ exit 0 } else { exit 1 } } catch { exit 1 }" >nul 2>&1
if not errorlevel 1 (
    echo [INFO] 端口 5000 已有健康服务，跳过后端启动。
    goto :start_frontend
)

echo [1/2] 启动后端（xcagi-backend-desktop.cmd）...
start "XCAGI Desktop Backend" /D "%XCAGI_DIR%" cmd /k "set XCAGI_PRODUCT_SKU=%XCAGI_PRODUCT_SKU%&& call xcagi-backend-desktop.cmd"

set "BACKEND_READY=0"
for /L %%I in (1,1,45) do (
    powershell -NoProfile -Command "try { $r=Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:5000/api/health' -TimeoutSec 3; if($r.StatusCode -eq 200){ exit 0 } else { exit 1 } } catch { exit 1 }" >nul 2>&1
    if not errorlevel 1 (
        set "BACKEND_READY=1"
        goto :backend_ok
    )
    if %%I==1 echo [INFO] 等待 /api/health ...
    ping 127.0.0.1 -n 2 >nul
)
:backend_ok
if "!BACKEND_READY!"=="1" (
    echo [OK] 后端就绪: http://127.0.0.1:5000
) else (
    echo [WARN] 后端未就绪，请查看「XCAGI Desktop Backend」窗口。
)

:start_frontend
set "FRONTEND_DIR=%FHD_ROOT%\frontend"
if not exist "%FRONTEND_DIR%\package.json" (
    start "" "http://127.0.0.1:5000/"
    goto :done
)

netstat -ano | findstr /R /C:":5001 .*LISTENING" >nul 2>&1
if not errorlevel 1 goto :open_browser

echo [2/2] 启动前端 Vite（5001）...
start "XCAGI Desktop Frontend" /D "%FRONTEND_DIR%" cmd /k "npm run dev"
ping 127.0.0.1 -n 4 >nul

:open_browser
start "" "http://127.0.0.1:5001/"

:done
echo.
pause
goto :eof
