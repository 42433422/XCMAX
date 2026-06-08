@echo off
chcp 65001 >nul
title XCAGI MOD 商店
cd /d "%~dp0"

echo MOD 商店已并入主后端 /api/mod-store，无需单独 python -m modstore_server。
echo 请先运行 start-xcagi.bat（或自行启动前端 5173 + 后端 8000）。
echo.
echo 正在打开浏览器：/mod-store
start "" "http://127.0.0.1:5173/mod-store"
echo.
pause
