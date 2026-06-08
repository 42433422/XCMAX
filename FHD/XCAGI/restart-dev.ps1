# 开发环境重启：与仓库根 start-dev.bat 走同一套启动链（xcagi-backend-with-db.cmd → xcagi-backend.cmd）。
# 请勿仅用「python run.py」替代：会跳过 DATABASE_URL / Postgres / CORS 等初始化。
#
# Vite :5001 将 /api 代理到 FastAPI :5000（见 frontend/vite.config.js）。

$ErrorActionPreference = 'Continue'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$startDev = Join-Path $repoRoot 'start-dev.bat'

$ports = 5000, 5001
foreach ($port in $ports) {
    Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | ForEach-Object {
        $procId = $_.OwningProcess
        if ($procId) {
            Write-Host "  Stopping PID $procId (port $port)"
            Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
        }
    }
}

Start-Sleep -Seconds 2

if (-not (Test-Path -LiteralPath $startDev)) {
    Write-Error "start-dev.bat not found: $startDev"
    exit 1
}

Write-Host "Starting via: $startDev"
Start-Process -FilePath $startDev -WorkingDirectory $repoRoot
