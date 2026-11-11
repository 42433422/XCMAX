@echo off
setlocal EnableExtensions
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\scripts\package\build-backend.ps1" %*
exit /b %ERRORLEVEL%
