# Dot-source in PowerShell:  . .\scripts\fhd-set-database-url.ps1
$FhdRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$env:FHD_REPO_ROOT = $FhdRoot
$xcagi = Join-Path $FhdRoot 'XCAGI'
$envFile = Join-Path $xcagi '.env'

function Test-TcpPort([int]$Port) {
    try {
        $c = New-Object Net.Sockets.TcpClient
        $c.Connect('127.0.0.1', $Port)
        $c.Dispose()
        return $true
    } catch {
        return $false
    }
}

if (-not $env:DATABASE_URL -and (Test-Path -LiteralPath $envFile)) {
    Get-Content -LiteralPath $envFile | ForEach-Object {
        if ($_ -match '^\s*DATABASE_URL\s*=') {
            $env:DATABASE_URL = ($_.Split('=', 2)[1]).Trim()
        }
        if ($_ -match '^\s*VECTOR_DB_URL\s*=') {
            $env:VECTOR_DB_URL = ($_.Split('=', 2)[1]).Trim()
        }
    }
}

$p5433 = Test-TcpPort 5433
$p5432 = Test-TcpPort 5432

if (-not $env:DATABASE_URL) {
    if ($p5433) { $port = 5433 }
    elseif ($p5432) { $port = 5432 }
    else { $port = 5433 }
    $env:DATABASE_URL = "postgresql+psycopg://xcagi:xcagi@127.0.0.1:$port/xcagi"
}

$xcagiApp = Join-Path $xcagi 'app'
if (Test-Path -LiteralPath $xcagiApp) {
    $prefix = "$xcagi;$FhdRoot"
    if (-not $env:PYTHONPATH) {
        $env:PYTHONPATH = $prefix
    } elseif ($env:PYTHONPATH -notlike "*$xcagi*") {
        $env:PYTHONPATH = "$prefix;$($env:PYTHONPATH)"
    }
} elseif (-not $env:PYTHONPATH) {
    $env:PYTHONPATH = $FhdRoot
}
