# Restart the selected existing launcher without switching database modes.
param(
    [ValidateSet('desktop', 'web')]
    [string]$Mode = 'desktop'
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$startDev = if ($Mode -eq 'web') {
    Join-Path $PSScriptRoot 'start-dev.bat'
} else {
    Join-Path $repoRoot 'start-dev.bat'
}
if (-not (Test-Path -LiteralPath $startDev -PathType Leaf)) {
    Write-Error "start-dev.bat not found: $startDev"
    exit 1
}

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

Write-Host "Starting via: $startDev"
Start-Process -FilePath $startDev -WorkingDirectory (Split-Path -Parent $startDev) -ErrorAction Stop
