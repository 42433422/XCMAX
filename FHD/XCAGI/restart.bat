@echo off
setlocal EnableExtensions
call "%~dp0..\scripts\launchers\restart.bat" %*
set "XCAGI_LAUNCH_EXIT=%ERRORLEVEL%"
exit /b %XCAGI_LAUNCH_EXIT%
