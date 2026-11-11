@echo off
setlocal EnableExtensions
pushd "%~dp0.." || exit /b 1
call "%~dp0..\deploy.bat" %*
set "XCAGI_LAUNCH_EXIT=%ERRORLEVEL%"
popd
exit /b %XCAGI_LAUNCH_EXIT%
