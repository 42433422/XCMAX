param(
  [Parameter(Mandatory=$true)][ValidateSet('Clean','Upgrade')][string]$Mode,
  [Parameter(Mandatory=$true)][string]$CandidatePath,
  [Parameter(Mandatory=$true)][string]$CandidateSha,
  [Parameter(Mandatory=$true)][string]$EvidenceDir,
  [string]$OldPath = '',
  [string]$OldSha256 = '95b8d6b11adc204cc7b6f5e3ae62af648f6be0ee94604ad850d5b9a978e98e99'
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'product-version.ps1')
$productVersion = Resolve-ProductVersion
$installRoot = Join-Path $env:RUNNER_TEMP "xcagi-candidate-$Mode"
$dataRoot = Join-Path $env:APPDATA 'XCAGI'
$base = 'http://127.0.0.1:17500'
$evidence = [ordered]@{ mode=$Mode; candidate_sha=$CandidateSha; started_at=(Get-Date).ToUniversalTime().ToString('o'); checks=@(); result='running' }
New-Item -ItemType Directory -Force -Path $EvidenceDir | Out-Null
function Check([bool]$ok, [string]$name, [string]$detail) {
  $script:evidence.checks += @{ name=$name; passed=$ok; detail=$detail }
  if (-not $ok) { throw "$name failed: $detail" }
}
function Digest([string]$text) {
  $bytes = [Text.Encoding]::UTF8.GetBytes($text)
  $hash = [Security.Cryptography.SHA256]::Create().ComputeHash($bytes)
  return ([BitConverter]::ToString($hash) -replace '-', '').ToLowerInvariant()
}
function Stop-App {
  Get-Process -Name XCAGI,xcagi-backend -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
  Start-Sleep -Seconds 2
}
function Install([string]$path, [string]$label) {
  Check (Test-Path -LiteralPath $path) "$label.file" 'installer exists'
  $p = Start-Process -FilePath $path -ArgumentList @('/S',"/D=$installRoot") -Wait -PassThru
  Check ($p.ExitCode -eq 0) "$label.install" "exit=$($p.ExitCode)"
  Check (Test-Path (Join-Path $installRoot 'XCAGI.exe')) "$label.exe" 'installed executable exists'
}
function Start-App([string]$label) {
  $p = Start-Process -FilePath (Join-Path $installRoot 'XCAGI.exe') -WorkingDirectory $installRoot -PassThru
  $deadline = (Get-Date).AddMinutes(4)
  $health = $null; $status = $null
  while ((Get-Date) -lt $deadline) {
    $p.Refresh()
    Check (-not $p.HasExited) "$label.process" "pid=$($p.Id) remains running"
    try {
      $health = Invoke-RestMethod "$base/api/health" -TimeoutSec 3
      $status = Invoke-RestMethod "$base/api/desktop/status" -TimeoutSec 3
      if ($health.status -eq 'healthy' -and $status.readyForUi -eq $true) { break }
    } catch { }
    Start-Sleep -Seconds 2
  }
  Check ($health.status -eq 'healthy' -and $status.readyForUi -eq $true) "$label.first_start_ready" "health=$($health.status); readyForUi=$($status.readyForUi); pid=$($p.Id)"
  $p.Refresh()
  Check (-not $p.HasExited) "$label.no_restart" "original pid=$($p.Id)"
  return $p
}
function Login([string]$label) {
  Check ([bool]$env:XCAGI_TEST_USER -and [bool]$env:XCAGI_TEST_PASS) "$label.credentials" 'CI test credentials are configured'
  $session = New-Object Microsoft.PowerShell.Commands.WebRequestSession
  $body = @{ username=$env:XCAGI_TEST_USER; password=$env:XCAGI_TEST_PASS } | ConvertTo-Json -Compress
  try {
    $r = Invoke-WebRequest "$base/api/auth/login" -Method Post -Body $body -ContentType 'application/json' -WebSession $session -TimeoutSec 30
    $http = [int]$r.StatusCode
    $j = $r.Content | ConvertFrom-Json
  } catch {
    $http = [int]$_.Exception.Response.StatusCode
    Check $false "$label.login" "http=$http"
  }
  Check ($http -eq 200 -and $j.success -eq $true) "$label.login" "http=$http; success=$($j.success)"
  $me = Invoke-RestMethod "$base/api/auth/me" -WebSession $session -TimeoutSec 15
  $identity = $me.data
  $kind = [string]$identity.account_kind
  if (-not $kind) { $kind = [string]$identity.user.account_kind }
  $tenant = [string]$identity.tenant_id
  if (-not $tenant) { $tenant = [string]$identity.tenant.id }
  if (-not $tenant) { $tenant = [string]$identity.user.tenant_id }
  Check ($kind -eq 'enterprise' -and $tenant) "$label.enterprise" "kind=$kind; tenant_sha256=$(Digest $tenant)"
  return @{ session=$session; tenant=$tenant }
}
function Read-Record($session, [int]$id, [string]$marker, [string]$label) {
  $r = Invoke-WebRequest "$base/api/customers/$id" -WebSession $session -TimeoutSec 20
  $seen = $r.Content.Contains($marker)
  Check ([int]$r.StatusCode -eq 200 -and $seen) "$label.read_record" "http=$($r.StatusCode); marker_sha256=$(Digest $marker); seen=$seen"
}
function Create-Record($session, [string]$marker, [string]$label) {
  $body = @{unit_name=$marker; contact_name='Acceptance'; phone=''; address=''} | ConvertTo-Json -Compress
  $r = Invoke-WebRequest "$base/api/customers" -Method Post -Body $body -ContentType 'application/json' -WebSession $session -TimeoutSec 20
  Check ([int]$r.StatusCode -eq 200) "$label.create_record" "http=$($r.StatusCode); marker_sha256=$(Digest $marker)"
  $id = [int](($r.Content | ConvertFrom-Json).data.id)
  Check ($id -gt 0) "$label.record_id" "id=$id"
  Read-Record $session $id $marker $label
  return $id
}
function Backup-And-Version {
  $infoPath = Join-Path $installRoot 'resources/build-info.json'
  $info = Get-Content $infoPath -Raw | ConvertFrom-Json
  Check ($info.gitSha -eq $CandidateSha -and $info.version -eq $productVersion) 'build_info' "sha=$($info.gitSha); version=$($info.version)"
  $display = @('HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*','HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*') | ForEach-Object { Get-ItemProperty $_ -ErrorAction SilentlyContinue } | Where-Object { $_.InstallLocation -eq $installRoot } | Select-Object -First 1
  Check ($display.DisplayVersion -eq $productVersion) 'installer_display_version' "display=$($display.DisplayVersion)"
  $daily = Get-ScheduledTask -TaskName XcagiDailyBackup -ErrorAction Stop
  $weekly = Get-ScheduledTask -TaskName XcagiWeeklyBackup -ErrorAction Stop
  Check ($daily.Actions[0].Execute -match 'powershell.exe' -and $daily.Actions[0].Arguments -match 'XcagiBackup.ps1') 'backup_task_action' 'daily and weekly tasks registered; daily action points to packaged backup script'
  Check ($weekly.Triggers.Count -gt 0) 'backup_weekly_trigger' 'weekly trigger exists'
  $started = Get-Date
  Start-ScheduledTask -TaskName XcagiDailyBackup
  $deadline = (Get-Date).AddMinutes(2)
  do { Start-Sleep -Seconds 3; $task = Get-ScheduledTaskInfo -TaskName XcagiDailyBackup } while ($task.LastRunTime -lt $started -and (Get-Date) -lt $deadline)
  Check ($task.LastRunTime -ge $started -and $task.LastTaskResult -eq 0) 'backup_task_run' "last_result=$($task.LastTaskResult)"
  $backup = Get-ChildItem (Join-Path $dataRoot 'backups') -Filter 'xcagi-*.db' -File -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
  Check ($null -ne $backup -and $backup.Length -gt 0) 'backup_file' "bytes=$($backup.Length)"
}
try {
  Check (-not (Test-Path $dataRoot) -and -not (Test-Path $installRoot)) 'isolated_runner' 'fresh user data and install path'
  Check (-not (Get-ScheduledTask -TaskName XcagiDailyBackup -ErrorAction SilentlyContinue)) 'isolated_tasks' 'no prior daily task'
  $candidateHash = (Get-FileHash -LiteralPath $CandidatePath -Algorithm SHA256).Hash.ToLowerInvariant()
  $evidence.candidate_sha256 = $candidateHash
  if ($Mode -eq 'Upgrade') {
    Check ((Get-FileHash -LiteralPath $OldPath -Algorithm SHA256).Hash.ToLowerInvariant() -eq $OldSha256) 'old_installer_hash' "sha256=$OldSha256"
    Install $OldPath 'old'
    $oldProcess = Start-App 'old'
    $oldAuth = Login 'old'
    $marker = "ACCEPT-UPGRADE-$env:GITHUB_RUN_ID-$env:GITHUB_RUN_ATTEMPT"
    $recordId = Create-Record $oldAuth.session $marker 'before_upgrade'
    Stop-App
    Install $CandidatePath 'candidate'
    $newProcess = Start-App 'candidate'
    $newAuth = Login 'candidate'
    Check ($newAuth.tenant -eq $oldAuth.tenant) 'same_enterprise' "tenant_sha256=$(Digest $newAuth.tenant)"
    Read-Record $newAuth.session $recordId $marker 'after_upgrade'
  } else {
    Install $CandidatePath 'candidate'
    $newProcess = Start-App 'candidate'
    $newAuth = Login 'candidate'
    $marker = "ACCEPT-CLEAN-$env:GITHUB_RUN_ID-$env:GITHUB_RUN_ATTEMPT"
    Create-Record $newAuth.session $marker 'clean'
  }
  Backup-And-Version
  $evidence.result = 'passed'
} catch {
  $evidence.result = 'failed'
  $evidence.failure = $_.Exception.Message
  throw
} finally {
  $evidence.finished_at = (Get-Date).ToUniversalTime().ToString('o')
  $evidence | ConvertTo-Json -Depth 8 | Set-Content (Join-Path $EvidenceDir 'acceptance.json') -Encoding utf8
  Stop-App
}
