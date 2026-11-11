@echo off
setlocal EnableExtensions
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "XCAGI_PHONE_LOOPBACK=0"
set "XCAGI_PHONE_USE_DEFAULT_MIC=1"
call "%~dp0start-dev.bat" %*
exit /b %ERRORLEVEL%
