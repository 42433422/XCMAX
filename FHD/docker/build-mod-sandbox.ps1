# Assembles a minimal build context (no --ignorefile required) and builds xcagi-mod-sandbox.
# Run from repository root:  powershell -File docker/build-mod-sandbox.ps1

$ErrorActionPreference = "Stop"
# 脚本位于 <repo>/docker/
$RepoRoot = (Get-Item $PSScriptRoot).Parent.FullName
$Ctx = Join-Path ([System.IO.Path]::GetTempPath()) ("xcagi-mod-sandbox-" + [guid]::NewGuid().ToString("n"))

try {
    New-Item -ItemType Directory -Path $Ctx | Out-Null
    foreach ($item in @('app', 'packages', 'config', 'resources', 'requirements-server-api.txt')) {
        Copy-Item -Recurse (Join-Path $RepoRoot $item) (Join-Path $Ctx $item)
    }
    Copy-Item (Join-Path $PSScriptRoot "Dockerfile.mod-sandbox") (Join-Path $Ctx "Dockerfile")

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
