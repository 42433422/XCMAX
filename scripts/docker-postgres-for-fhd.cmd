@echo off
setlocal EnableExtensions EnableDelayedExpansion
REM Start XCAGI Postgres via Docker Compose (service name: postgres).

pushd "%~dp0.."
set "FHD_ROOT=!CD!"
if "!FHD_ROOT:~-1!"=="\" set "FHD_ROOT=!FHD_ROOT:~0,-1!"
popd

set "XCAGI_DIR=!FHD_ROOT!\XCAGI"
if not exist "!XCAGI_DIR!\docker-compose.yml" (
  echo [WARN] docker-postgres-for-fhd: missing !XCAGI_DIR!\docker-compose.yml
  exit /b 1
)

set "DOCKER_EXE="
if exist "C:\Program Files\Docker\Docker\resources\bin\docker.exe" (
  set "DOCKER_EXE=C:\Program Files\Docker\Docker\resources\bin\docker.exe"
) else if exist "C:\Program Files (x86)\Docker\Docker\resources\bin\docker.exe" (
  set "DOCKER_EXE=C:\Program Files (x86)\Docker\Docker\resources\bin\docker.exe"
)
if not defined DOCKER_EXE (
  where docker >nul 2>&1 && for /f "delims=" %%D in ('where docker') do set "DOCKER_EXE=%%D"
)

if not defined DOCKER_EXE (
  echo [WARN] docker-postgres-for-fhd: docker.exe not found
  exit /b 1
)

pushd "!XCAGI_DIR!"
"!DOCKER_EXE!" compose up -d postgres
set "DOCKER_UP=!ERRORLEVEL!"
if not "!DOCKER_UP!"=="0" (
  for %%D in ("!DOCKER_EXE!") do set "DOCKER_BIN_DIR=%%~dpD"
  if exist "!DOCKER_BIN_DIR!docker-compose.exe" (
    "!DOCKER_BIN_DIR!docker-compose.exe" up -d postgres
    set "DOCKER_UP=!ERRORLEVEL!"
  ) else (
    echo [WARN] docker-postgres-for-fhd: compose failed and docker-compose.exe not found.
  )
)
popd
exit /b %DOCKER_UP%
