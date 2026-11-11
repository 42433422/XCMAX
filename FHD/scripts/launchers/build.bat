@echo off
setlocal EnableExtensions
call "%~dp0..\..\XCAGI\build.bat" %*
set "XCAGI_LAUNCH_EXIT=%ERRORLEVEL%"
exit /b %XCAGI_LAUNCH_EXIT%
