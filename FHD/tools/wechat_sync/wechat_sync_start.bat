@echo off
rem 微信聊天记录同步代理启动器（Windows）
rem 职责：选 Python → 循环拉起 wechat_sync.py --loop → 进程崩溃后 60 秒自动重启。
rem 依赖配置：同目录 wechat_sync_config.json（见 wechat_sync_config.json.example）。
rem 开机自启：以管理员运行 wechat_sync_install_task.ps1 注册计划任务（任务也调用本脚本）。

setlocal
chcp 65001 >nul
cd /d "%~dp0"
title XCAGI WeChat Sync

set PY=
if exist "..\..\.venv\Scripts\python.exe" set PY=..\..\.venv\Scripts\python.exe
if "%PY%"=="" (
    where py >nul 2>nul && set PY=py -3
)
if "%PY%"=="" (
    where python >nul 2>nul && set PY=python
)
if "%PY%"=="" (
    echo [wechat_sync] 未找到 Python，请安装 Python 3.10+ 或创建项目 .venv
    pause
    exit /b 1
)

:restart
echo [%date% %time%] 启动同步代理...
%PY% wechat_sync.py --loop
echo [%date% %time%] 同步代理退出（码 %errorlevel%），60 秒后自动重启。按 Ctrl+C 停止。
timeout /t 60 /nobreak >nul
goto restart
