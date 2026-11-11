@echo off
setlocal EnableExtensions
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0restart-dev.ps1" -Mode web %*
exit /b %ERRORLEVEL%
