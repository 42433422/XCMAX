@echo off
setlocal EnableExtensions
call "%~dp0..\scripts\launchers\logs.bat" %*
set "XCAGI_LAUNCH_EXIT=%ERRORLEVEL%"
exit /b %XCAGI_LAUNCH_EXIT%
