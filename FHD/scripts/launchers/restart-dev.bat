@echo off
setlocal EnableExtensions
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\..\XCAGI\restart-dev.ps1" -Mode desktop %*
exit /b %ERRORLEVEL%
