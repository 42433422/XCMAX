@echo off
chcp 65001 >nul
cd /d "%~dp0"

set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

echo [0/2] 释放端口 8765（若已占用）...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue ^| ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }"
timeout /t 1 /nobreak >nul

start "MODstore API" cmd /k "cd /d ""%~dp0"" && ""%PY%"" -m pip install -q -e ".[web,knowledge]" 2>nul && ""%PY%"" -m modstore_server"

timeout /t 2 /nobreak >nul

cd /d "%~dp0market"
if not exist "node_modules\" call npm install
start "MODstore Market" cmd /k "cd /d ""%~dp0market"" && npm run dev"

echo.
echo 市场前端: http://127.0.0.1:5176  ^(Vite，代理 /api 到 8765^)
echo API 健康:  http://127.0.0.1:8765/api/health
exit /b 0
