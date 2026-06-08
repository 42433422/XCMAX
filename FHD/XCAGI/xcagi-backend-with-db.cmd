@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "FHD_SCRIPTS=%~dp0..\scripts"

if exist "%FHD_SCRIPTS%\docker-postgres-for-fhd.cmd" (
  call "%FHD_SCRIPTS%\docker-postgres-for-fhd.cmd"
) else (
  echo [WARN] Missing script: %FHD_SCRIPTS%\docker-postgres-for-fhd.cmd
)

if exist "%FHD_SCRIPTS%\fhd-set-database-url.cmd" (
  call "%FHD_SCRIPTS%\fhd-set-database-url.cmd"
) else (
  echo [WARN] Missing script: %FHD_SCRIPTS%\fhd-set-database-url.cmd
)

if exist "%~dp0.venv\Scripts\python.exe" (
  set "PY_EXE=%~dp0.venv\Scripts\python.exe"
) else if exist "%~dp0..\.venv\Scripts\python.exe" (
  set "PY_EXE=%~dp0..\.venv\Scripts\python.exe"
) else (
  set "PY_EXE=python"
)

echo [INFO] DATABASE_URL=%DATABASE_URL%
echo [INFO] Python: %PY_EXE%

echo [INFO] Ensuring per-mod PostgreSQL databases (bootstrap + migrate if missing)...
"%PY_EXE%" "%~dp0..\scripts\bootstrap_mod_dbs.py"
if errorlevel 1 (
  echo [WARN] bootstrap_mod_dbs.py failed; ERP/Mod pages may 500 until fixed.
) else (
  "%PY_EXE%" "%~dp0..\scripts\migrate_mod_dbs.py"
  if errorlevel 1 echo [WARN] migrate_mod_dbs.py failed for one or more mod databases.
)

REM Updated 2026-04-17: FastAPI now runs on unified port 5000 (backend.http_app:8000 deleted)
REM Vite dev server (frontend port 5001) proxies /api to FastAPI port 5000
call "%~dp0xcagi-backend.cmd"
exit /b %errorlevel%
