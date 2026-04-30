@echo off
chcp 65001 >nul
title XCAGI v7.0 局域网启动器
setlocal EnableExtensions EnableDelayedExpansion

REM cd to script dir first (relative paths and UAC cwd)
cd /d "%~dp0"

echo.
echo ========================================
echo        XCAGI v7.0 LAN Launcher
echo ========================================
echo.

set "WANT_ADMIN="
set "CONFIGURE_FW="
set "SKIP_MENU="

:parse_args
if "%~1"=="" goto args_done
if /I "%~1"=="all" set "SKIP_MENU=1" & shift & goto parse_args
if /I "%~1"=="/all" set "SKIP_MENU=1" & shift & goto parse_args
REM /NoAdmin 和 --no-admin 目前等价于无参数（WANT_ADMIN 默认本就不设置）
REM 保留此处供将来扩展（如某些场景需要显式禁用提权）
if /I "%~1"=="/NoAdmin" shift & goto parse_args
if /I "%~1"=="--no-admin" shift & goto parse_args
if /I "%~1"=="/Admin" set "WANT_ADMIN=1" & shift & goto parse_args
if /I "%~1"=="/Firewall" set "WANT_ADMIN=1" & set "CONFIGURE_FW=1" & shift & goto parse_args
shift
goto parse_args
:args_done

REM UAC re-launch: pass only /Admin or /Firewall as single arg
if defined WANT_ADMIN (
    net session >nul 2>&1
    if errorlevel 1 (
        echo [提示] 已请求管理员权限 UAC ...
        if defined CONFIGURE_FW (
            echo        原因: 已指定 /Firewall，需管理员才能添加入站规则。
            set "ELEV_ARG=/Firewall"
        ) else (
            echo        原因: 已指定 /Admin，不会修改防火墙。
            set "ELEV_ARG=/Admin"
        )
        echo        若不需要高权限，请直接双击本脚本且不要加参数。
        powershell -NoProfile -Command "Start-Process -LiteralPath '%~f0' -Verb RunAs -ArgumentList \"!ELEV_ARG!\""
        exit /b
    )
)

set "FWOPT="
if defined CONFIGURE_FW set "FWOPT=-ConfigureFirewall"

REM 计算仓库根 ..\..\ 回到仓库根目录
set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "REPO_ROOT=%%~fI"
if not exist "%REPO_ROOT%\XCAGI\run.py" (
    echo [错误] 无法定位 XCAGI\run.py,期望的仓库根: %REPO_ROOT%
    echo        请确保本脚本位于 ^<仓库根^>\scripts\launchers\ 目录下。
    echo.
    pause
    exit /b 1
)
cd /d "%REPO_ROOT%"

if defined SKIP_MENU (
    echo.
    echo [INFO] 命令行已指定 all：直接启动后端 + 前端 ^(Vite dev^)，不再询问菜单。
    goto START_ALL
)

REM 显示选项
echo 当前仓库根: %REPO_ROOT%
net session >nul 2>&1
if errorlevel 1 (
    echo 权限       : 当前用户 ^(未提权^)
) else (
    echo 权限       : 管理员
)
if defined CONFIGURE_FW (
    echo 防火墙     : 将尝试放行 TCP 5000/5001 ^(由 start-lan.ps1 执行^)
) else (
    echo 防火墙     : 不修改 ^(局域网连不上时再运行: start-lan.bat /Firewall^)
)
echo.
echo [1] All dev       - backend + frontend, hot reload
echo [2] Backend only  - port 5000
echo [3] Frontend only - port 5001 Vite
echo [4] Stop          - kill repo python/node
echo [5] All + firewall - TCP 5000/5001 inbound ^(admin UAC^)
echo [6] Backend + firewall ^(admin UAC^)
echo [7] Frontend + firewall ^(admin UAC^)
echo [0] Exit
echo.
echo CLI: start-lan.bat /Firewall   same as menu 5-7
echo Args: /Admin   /Firewall   ^(append in shortcut Target^)
echo.
echo Tip: PowerShell window lists LAN URLs for phones on same WiFi.
echo      （菜单为英文：避免 cmd 将括号、加号、逗号等误解析为命令）
echo.
echo [快捷] start-lan.bat all   跳过本菜单，直接前后端一起启动。
echo.
REM choice 的 /M 必须用纯 ASCII：中文、加号、括号在 cmd 下会破坏解析，出现「xxx 不是内部或外部命令」。
echo 请按数字键；与上表对应。25 秒内不按则自动选 1 ^(前后端一起启动^)。
choice /C 12345670 /T 25 /D 1 /N /M "Press 1-7 or 0. See menu above. Timeout 25s default 1: "

if errorlevel 8 goto END
if errorlevel 7 goto START_FRONTEND_FW
if errorlevel 6 goto START_BACKEND_FW
if errorlevel 5 goto START_ALL_FW
if errorlevel 4 goto STOP_ALL
if errorlevel 3 goto START_FRONTEND
if errorlevel 2 goto START_BACKEND
if errorlevel 1 goto START_ALL
goto END

:MaybeElevateFirewall
net session >nul 2>&1
if not errorlevel 1 exit /b 0
echo.
echo [提示] 放行 TCP 5000/5001 需要管理员权限。将弹出 UAC；请在新窗口中确认完成。
echo        该窗口内应出现 Firewall rules OK 后自动返回此处。
echo.
REM 注意：不得把本段包在圆括号块里，否则 SCRIPT_DIR 会在块解析阶段被提前展开为空，导致提权窗口找不到 ps1 而卡在 pause。
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath powershell.exe -Verb RunAs -Wait -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-LiteralPath','%SCRIPT_DIR%start-lan.ps1','-ConfigureFirewallOnly'"
echo.
echo 放行步骤已结束。若取消 UAC-请右键本脚本以管理员身份运行后重试-或命令行 start-lan.bat /Firewall
pause
exit /b 0

:START_ALL_FW
call :MaybeElevateFirewall
set "FWOPT="
net session >nul 2>&1
if not errorlevel 1 set "FWOPT=-ConfigureFirewall"
goto START_ALL

:START_BACKEND_FW
call :MaybeElevateFirewall
set "FWOPT="
net session >nul 2>&1
if not errorlevel 1 set "FWOPT=-ConfigureFirewall"
goto START_BACKEND

:START_FRONTEND_FW
call :MaybeElevateFirewall
set "FWOPT="
net session >nul 2>&1
if not errorlevel 1 set "FWOPT=-ConfigureFirewall"
goto START_FRONTEND

:START_ALL
echo.
echo [INFO] 正在启动前后端服务 ^(不附加 -NoFrontend / -NoBackend，由 start-lan.ps1 同时起 Vite^)...
powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%start-lan.ps1" %FWOPT%
goto END

:START_BACKEND
echo.
echo [INFO] 正在启动后端服务...
powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%start-lan.ps1" -NoFrontend %FWOPT%
goto END

:START_FRONTEND
echo.
echo [INFO] 正在启动前端服务...
powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%start-lan.ps1" -NoBackend %FWOPT%
goto END

:STOP_ALL
echo.
echo [INFO] 正在停止本仓库相关的 python.exe / node.exe ...
powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%start-lan.ps1" -StopOnly
echo [√] 服务已停止
timeout /t 2 >nul
goto END

:END
echo.
echo 按任意键退出...
pause >nul
endlocal
