# bootstrap.ps1 - one-shot bootstrap for the base-login Windows acceptance round.
# ASCII-only source (Windows PowerShell 5.1 decodes BOM-less files as ANSI).
#
# Usage from a Windows PowerShell on the target machine:
#   $env:XCAGI_MODE='selftest'; iex(irm '<raw url of this file>')     # read-only recon, no credential needed
#   $env:XCAGI_MODE='full';     iex(irm '<raw url of this file>')     # full round (W1-W6 + six-element packaging)
#
# Optional env:
#   XCAGI_TEST_USER   acceptance account (default SUNBIRD)
#   XCAGI_TEST_PASS   acceptance password; when unset it is read from the existing
#                     main-branch acceptance script (the credential is already public in this repo,
#                     so this avoids adding yet another copy)
#   XCAGI_INSTALLER   installer path, recorded into the evidence identity
#   XCAGI_OUT         evidence output dir (default %TEMP%\xcagi-base-login-evidence)

$ErrorActionPreference = 'Stop'
$Ref = if ($env:XCAGI_REF) { $env:XCAGI_REF } else { 'evidence/feature-acceptance-base-login-20260922' }
$Base = "https://raw.githubusercontent.com/42433422/XCMAX/$Ref/FHD/docs/evidence/e2e/feature-acceptance-20260922/base-login/windows"
$Dir = Join-Path $env:TEMP 'xcagi-base-login'
New-Item -ItemType Directory -Force -Path $Dir | Out-Null
Write-Host "bootstrap: ref=$Ref"
Write-Host "bootstrap: dir=$Dir"

Invoke-WebRequest -Uri "$Base/accept-base-login.ps1" -OutFile (Join-Path $Dir 'accept-base-login.ps1') -UseBasicParsing
Write-Host 'bootstrap: fetched accept-base-login.ps1'
try {
    Invoke-WebRequest -Uri "$Base/drive-gui.js" -OutFile (Join-Path $Dir 'drive-gui.js') -UseBasicParsing
    Write-Host 'bootstrap: fetched drive-gui.js'
} catch {
    Write-Host ('bootstrap: drive-gui.js fetch failed (optional): ' + $_.Exception.Message)
}

if (-not $env:XCAGI_TEST_USER) { $env:XCAGI_TEST_USER = 'SUNBIRD' }

$Mode = if ($env:XCAGI_MODE) { $env:XCAGI_MODE } else { 'selftest' }
if ($Mode -ne 'selftest' -and -not $env:XCAGI_TEST_PASS) {
    $src = 'https://raw.githubusercontent.com/42433422/XCMAX/main/FHD/scripts/package/acceptance-sunbird-windows.ps1'
    try {
        $txt = (Invoke-WebRequest -Uri $src -UseBasicParsing).Content
        if ($txt -match "Password\s*=\s*'([^']+)'") {
            $env:XCAGI_TEST_PASS = $Matches[1]
            Write-Host 'bootstrap: credential loaded from the existing main-branch acceptance script'
        } else {
            Write-Host 'bootstrap: could not parse a password from the main-branch script'
        }
    } catch {
        Write-Host ('bootstrap: credential fetch failed: ' + $_.Exception.Message)
    }
}
if ($env:XCAGI_TEST_PASS) { Write-Host 'bootstrap: credential present' } else { Write-Host 'bootstrap: credential absent' }

$Out = if ($env:XCAGI_OUT) { $env:XCAGI_OUT } else { (Join-Path $env:TEMP 'xcagi-base-login-evidence') }
$argv = @('-ExecutionPolicy', 'Bypass', '-File', (Join-Path $Dir 'accept-base-login.ps1'), '-OutDir', $Out)
if ($Mode -eq 'selftest') {
    $argv += '-SelfTest'
} else {
    $argv += '-WithVideo'
    if ($env:XCAGI_INSTALLER) { $argv += @('-InstallerPath', $env:XCAGI_INSTALLER) }
}
Write-Host ('bootstrap: mode=' + $Mode + ' out=' + $Out)
& powershell @argv
Write-Host ('bootstrap: done, exit=' + $LASTEXITCODE)
if (Test-Path (Join-Path $Out 'base-login-windows.json')) {
    Write-Host '--- base-login-windows.json (head) ---'
    Get-Content (Join-Path $Out 'base-login-windows.json') -TotalCount 40
}