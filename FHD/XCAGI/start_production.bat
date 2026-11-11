@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "XCAGI_ENV=production"
set "XCAGI_UVICORN_RELOAD=0"
set "XCAGI_DEBUG=0"
set "XCAGI_PYTHON=python"
if exist "%~dp0..\.venv\Scripts\python.exe" set "XCAGI_PYTHON=%~dp0..\.venv\Scripts\python.exe"
if exist "%~dp0.venv\Scripts\python.exe" set "XCAGI_PYTHON=%~dp0.venv\Scripts\python.exe"
"%XCAGI_PYTHON%" "%~dp0run_fastapi.py" --host 0.0.0.0 --port 5000 %*
exit /b %ERRORLEVEL%
