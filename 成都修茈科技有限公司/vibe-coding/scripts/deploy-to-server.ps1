<#
.SYNOPSIS
  Sync vibe-coding/ (and optionally eskill-prototype/) to the deploy server,
  install both packages in editable mode, and run the test suites as a smoke
  check. Mirrors the style of MODstore_deploy/scripts/sync-modstore-to-server.ps1
  (tar -> scp -> remote bash) so it works in the same environment without git.

.PARAMETER SshTarget
  e.g. root@119.27.178.147 (default: env DEPLOY_SSH or that IP).

.PARAMETER RemoteBase
  Parent directory on the server. Default: /root/modstore-git
  (a symlink to /root/成都修茈科技有限公司 on the production machine).

.PARAMETER IncludeEskill
  When set, also pack and ship eskill-prototype/ (so the upstream main version
  is available on the server too). Off by default to keep the diff minimal.

.PARAMETER SkipTests
  Skip the remote pytest smoke run.

.EXAMPLE
  .\scripts\deploy-to-server.ps1                 # just vibe-coding/
  .\scripts\deploy-to-server.ps1 -IncludeEskill  # both packages
#>
param(
  [string] $SshTarget = $env:DEPLOY_SSH,
  [string] $RemoteBase = $env:DEPLOY_REMOTE_BASE,
  [switch] $IncludeEskill,
  [switch] $SkipTests
)

$ErrorActionPreference = "Stop"
if (-not $SshTarget) { $SshTarget = "root@119.27.178.147" }
if (-not $RemoteBase) { $RemoteBase = "/root/modstore-git" }

# script lives in vibe-coding/scripts/  →  vibe-coding/
$VibeCodingRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$CompanyRoot = Split-Path -Parent $VibeCodingRoot
$EskillRoot = Join-Path $CompanyRoot "eskill-prototype"

if (-not (Test-Path $VibeCodingRoot)) { throw "vibe-coding root not found: $VibeCodingRoot" }
if ($IncludeEskill -and -not (Test-Path $EskillRoot)) {
  throw "eskill-prototype root not found: $EskillRoot"
}

$TarName = "vibe_coding_sync.tgz"
$LocalTar = Join-Path $env:TEMP $TarName

Write-Host "[deploy] target: $SshTarget  remote_base: $RemoteBase"
Write-Host "[deploy] vibe-coding: $VibeCodingRoot"
if ($IncludeEskill) { Write-Host "[deploy] eskill-prototype: $EskillRoot" }
Write-Host "[deploy] 1/4 creating tar..."

$excludes = @(
  "vibe-coding/.venv"
  "vibe-coding/.pytest_cache"
  "vibe-coding/.ruff_cache"
  "vibe-coding/__pycache__"
  "vibe-coding/src/vibe_coding/__pycache__"
  "vibe-coding/src/vibe_coding/_internals/__pycache__"
  "vibe-coding/src/vibe_coding/runtime/__pycache__"
  "vibe-coding/src/vibe_coding/nl/__pycache__"
  "vibe-coding/tests/__pycache__"
  "vibe-coding/build"
  "vibe-coding/dist"
  "vibe-coding/*.egg-info"
  "vibe-coding/vibe_coding_data"
)
if ($IncludeEskill) {
  $excludes += @(
    "eskill-prototype/.venv"
    "eskill-prototype/.pytest_cache"
    "eskill-prototype/.ruff_cache"
    "eskill-prototype/.git"
    "eskill-prototype/__pycache__"
    "eskill-prototype/src/eskill/__pycache__"
    "eskill-prototype/src/eskill/code/__pycache__"
    "eskill-prototype/src/eskill/vibe_coding/__pycache__"
    "eskill-prototype/src/eskill/vibe_coding/nl/__pycache__"
    "eskill-prototype/tests/__pycache__"
    "eskill-prototype/build"
    "eskill-prototype/dist"
    "eskill-prototype/*.egg-info"
    "eskill-prototype/data"
  )
}

Push-Location $CompanyRoot
try {
  if (Test-Path $LocalTar) { Remove-Item -Force $LocalTar }
  $argsT = @("-czf", $LocalTar)
  foreach ($e in $excludes) { $argsT += "--exclude=$e" }
  $argsT += "vibe-coding"
  if ($IncludeEskill) { $argsT += "eskill-prototype" }
  $p = Start-Process -FilePath "tar" -ArgumentList $argsT -NoNewWindow -PassThru -Wait
  if ($p.ExitCode -ne 0) { throw "tar failed exit=$($p.ExitCode)" }
} finally {
  Pop-Location
}

$mb = [math]::Round((Get-Item $LocalTar).Length / 1MB, 2)
Write-Host "[deploy] tgz: $mb MB  $LocalTar"

Write-Host "[deploy] 2/4 scp tgz + bootstrap..."
$enc = [System.Text.UTF8Encoding]::new($false)

$bootstrap = Join-Path $VibeCodingRoot "scripts/remote_install_vibe_coding.sh"
if (-not (Test-Path $bootstrap)) { throw "missing remote installer: $bootstrap" }
$bootContent = [System.IO.File]::ReadAllText($bootstrap, [System.Text.Encoding]::UTF8)
$bootContent = $bootContent -replace "`r`n", "`n" -replace "`r", "`n"
$bootTmp = Join-Path $env:TEMP "remote_install_vibe_coding_$(Get-Date -Format 'yyyyMMddHHmmss').sh"
[System.IO.File]::WriteAllText($bootTmp, $bootContent, $enc)

$null = & scp -o BatchMode=yes -q $LocalTar ($SshTarget + ":/tmp/") 2>&1
if ($LASTEXITCODE -ne 0) { throw "scp tgz failed exit=$LASTEXITCODE" }
$null = & scp -o BatchMode=yes -q $bootTmp ($SshTarget + ":/tmp/remote_install_vibe_coding.sh") 2>&1
if ($LASTEXITCODE -ne 0) { throw "scp installer failed exit=$LASTEXITCODE" }
Remove-Item -Force $bootTmp -ErrorAction SilentlyContinue

# Pass remote base as base64 for non-ASCII safety (matches MODstore deploy convention)
$b64 = [Convert]::ToBase64String($enc.GetBytes($RemoteBase))
$envParts = @("REMOTE_BASE_B64=$b64")
if ($IncludeEskill) { $envParts += "INCLUDE_ESKILL=1" }
if ($SkipTests) { $envParts += "SKIP_TESTS=1" }
$envStr = ($envParts -join " ")

Write-Host "[deploy] 3/4 on server: extract + pip install -e + pytest..."
$remote = "chmod +x /tmp/remote_install_vibe_coding.sh; $envStr bash /tmp/remote_install_vibe_coding.sh; ec=`$?; rm -f /tmp/remote_install_vibe_coding.sh; exit `$ec"
ssh -o BatchMode=yes $SshTarget $remote
$exit = $LASTEXITCODE

Write-Host "[deploy] 4/4 local tgz still at: $LocalTar"
if ($exit -ne 0) { exit $exit }
Write-Host "[deploy] done."
