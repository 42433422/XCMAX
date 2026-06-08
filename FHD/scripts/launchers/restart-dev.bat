@echo off
setlocal EnableExtensions
cd /d "%~dp0"
REM 与双击 start-dev.bat 相同启动链；本脚本会先释放 5000/5001 再拉起前后端。
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0XCAGI\restart-dev.ps1"
exit /b %ERRORLEVEL%
