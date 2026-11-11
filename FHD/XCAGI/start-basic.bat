@echo off
setlocal EnableExtensions
call "%~dp0start-dev.bat" %*
set "XCAGI_LAUNCH_EXIT=%ERRORLEVEL%"
exit /b %XCAGI_LAUNCH_EXIT%
