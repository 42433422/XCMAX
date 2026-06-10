# Assembles a minimal build context (no --ignorefile required) and builds xcagi-mod-sandbox.
# Run from repository root:  powershell -File docker/mod-sandbox/build.ps1

$ErrorActionPreference = "Stop"
# 本脚本位于 <repo>/docker/mod-sandbox/
$RepoRoot = (Get-Item $PSScriptRoot).Parent.Parent.FullName
$Ctx = Join-Path ([System.IO.Path]::GetTempPath()) ("xcagi-mod-sandbox-" + [guid]::NewGuid().ToString("n"))

try {
    New-Item -ItemType Directory -Path $Ctx | Out-Null
    Copy-Item -Recurse (Join-Path $RepoRoot "app") (Join-Path $Ctx "app")
    New-Item -ItemType Directory -Path (Join-Path $Ctx "XCAGI") | Out-Null
    Copy-Item (Join-Path $RepoRoot "XCAGI\requirements.txt") (Join-Path $Ctx "XCAGI")
    Copy-Item (Join-Path $RepoRoot "XCAGI\run.py") (Join-Path $Ctx "XCAGI")
    Copy-Item (Join-Path $RepoRoot "XCAGI\run_fastapi.py") (Join-Path $Ctx "XCAGI")
    Copy-Item -Recurse (Join-Path $RepoRoot "resources") (Join-Path $Ctx "resources")
    Copy-Item (Join-Path $PSScriptRoot "Dockerfile") (Join-Path $Ctx "Dockerfile")

    Set-Location $Ctx
    docker build -t xcagi-mod-sandbox .
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}
finally {
    Set-Location $RepoRoot
    if (Test-Path $Ctx) {
        Remove-Item -Recurse -Force $Ctx -ErrorAction SilentlyContinue
    }
}
