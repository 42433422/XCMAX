@echo off
REM 生产环境启动脚本
REM 使用 Gunicorn + UvicornWorker（FastAPI ASGI）

echo 正在启动 XCAGI 生产服务器...

cd /d %~dp0

set XCAGI_ENV=production
set XCAGI_DEBUG=0

echo 启动 Gunicorn 服务器（UvicornWorker）...
python -m gunicorn -c gunicorn_config.py run:app

pause
