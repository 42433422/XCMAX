param(
  [Parameter(Mandatory=$true)][ValidateSet('Clean','Upgrade','Gui')][string]$Mode,
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
git merge-base --is-ancestor $CandidateSha origin/main
if ($LASTEXITCODE -gt 1) { throw 'Unable to verify candidate mainline ancestry' }
$evidence = [ordered]@{ mode=$Mode; candidate_sha=$CandidateSha; candidate_on_main=($LASTEXITCODE -eq 0); customer_acceptance='not_verified'; started_at=(Get-Date).ToUniversalTime().ToString('o'); checks=@(); result='running' }
$global:LASTEXITCODE = 0
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
  $p = Start-Process -FilePath $path -ArgumentList @('/S',"/D=$installRoot") -Wait -PassThru
  Check ($p.ExitCode -eq 0) "$label.install" "exit=$($p.ExitCode)"
  Check (Test-Path (Join-Path $installRoot 'XCAGI.exe')) "$label.exe" 'installed executable exists'
}
function Start-App([string]$label) {
  $launch = @{FilePath=(Join-Path $installRoot 'XCAGI.exe'); WorkingDirectory=$installRoot; PassThru=$true; WindowStyle='Hidden'}
  if ($Mode -in @('Gui','Upgrade')) { $launch.ArgumentList = @('--remote-debugging-port=9222') }
  $p = Start-Process @launch
  $deadline = (Get-Date).AddMinutes(4)
  $health = $null; $status = $null
  while ((Get-Date) -lt $deadline) {
    $p.Refresh()
    if ($p.HasExited) { Check $false "$label.process" "pid=$($p.Id) exited before ready" }
    try {
      $health = Invoke-RestMethod "$base/api/health?lite=true" -TimeoutSec 3
      $status = Invoke-RestMethod "$base/api/desktop/status" -TimeoutSec 3
      if ($health.status -ne 'unhealthy' -and @($health.runtime.blockers).Count -eq 0 -and $status.readyForUi -eq $true) { break }
    } catch { }
    Start-Sleep -Seconds 2
  }
  Check ($health.status -ne 'unhealthy' -and @($health.runtime.blockers).Count -eq 0 -and $status.readyForUi -eq $true) "$label.first_start_ready" "health=$($health.status); blockers=$(@($health.runtime.blockers).Count); readyForUi=$($status.readyForUi); pid=$($p.Id)"
  $listener = Get-NetTCPConnection -LocalPort 17500 -State Listen -ErrorAction Stop | Select-Object -First 1
  $backend = Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)"
  $dataArgument = [regex]::Match($backend.CommandLine, '--data-dir\s+(?:"([^"]+)"|(\S+))'); $actualDataRoot = if ($dataArgument.Groups[1].Success) { $dataArgument.Groups[1].Value } else { $dataArgument.Groups[2].Value }
  $expectedDataRoot = if ($env:XCAGI_DESKTOP_USER_DATA_DIR) { $env:XCAGI_DESKTOP_USER_DATA_DIR } else { $dataRoot }
  Check (($backend.ExecutablePath -match ('^' + [regex]::Escape($installRoot + [IO.Path]::DirectorySeparatorChar))) -and $dataArgument.Success -and $actualDataRoot -eq $expectedDataRoot) "$label.port_owner" "pid=$($backend.ProcessId); exe=$($backend.ExecutablePath); actual_data=$actualDataRoot; expected_data=$expectedDataRoot"
  $p.Refresh()
  Check (-not $p.HasExited) "$label.no_restart" "original pid=$($p.Id)"
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
    Check $false "$label.login" "http=$([int]$_.Exception.Response.StatusCode); error=$($_.Exception.GetType().Name): $($_.Exception.Message)"
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
function Read-Record($session, [string]$id, [string]$marker, [string]$label) {
  $r = Invoke-WebRequest "$base/api/agent/tasks/$id" -WebSession $session -TimeoutSec 20
  $seen = $r.Content.Contains($marker)
  Check ([int]$r.StatusCode -eq 200 -and $seen) "$label.read_record" "http=$($r.StatusCode); marker_sha256=$(Digest $marker); seen=$seen"
}
function Create-Record($session, [string]$marker, [string]$label) {
  $body = @{task_id=$marker; title=$marker; message=$marker; tool_id='dataset_rag'; action='query'; params=@{dataset_id='acceptance'; query=$marker}} | ConvertTo-Json -Compress
  Invoke-WebRequest "$base/api/health?lite=true" -WebSession $session -TimeoutSec 15 | Out-Null
  $csrf = @($session.Cookies.GetCookies([Uri]$base) | Where-Object { $_.Name -eq 'csrf_token' } | Select-Object -First 1)[0].Value
  Check ([bool]$csrf) "$label.csrf_cookie" 'safe request established a CSRF cookie'
  $r = Invoke-WebRequest "$base/api/agent/tasks" -Method Post -Body $body -ContentType 'application/json' -Headers @{'X-CSRF-Token'=$csrf} -WebSession $session -TimeoutSec 20
  Check ([int]$r.StatusCode -in @(200,202)) "$label.create_record" "http=$($r.StatusCode); marker_sha256=$(Digest $marker)"
  Read-Record $session $marker $marker $label
  return $marker
}
function Backup-And-Version {
  $infoPath = Join-Path $installRoot 'resources/build-info.json'
  $info = Get-Content $infoPath -Raw | ConvertFrom-Json
  Check ($info.gitSha -eq $CandidateSha -and $info.version -eq $productVersion) 'build_info' "sha=$($info.gitSha); version=$($info.version)"
  $display = @('HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*','HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*') | ForEach-Object { Get-ItemProperty $_ -ErrorAction SilentlyContinue } | Where-Object { $_.DisplayName -like 'XCAGI*' } | Select-Object -First 1
  Check ($display.DisplayVersion -eq $productVersion) 'installer_display_version' "display=$($display.DisplayVersion); expected=$productVersion"
  $daily = Get-ScheduledTask -TaskName XcagiDailyBackup -ErrorAction Stop
  $weekly = Get-ScheduledTask -TaskName XcagiWeeklyBackup -ErrorAction Stop
  $script:evidence.backup_tasks = @($daily, $weekly) | ForEach-Object { @{ name=$_.TaskName; user=$_.Principal.UserId; logon=[string]$_.Principal.LogonType; run_level=[string]$_.Principal.RunLevel; actions=@($_.Actions | Select-Object Execute,Arguments,WorkingDirectory); triggers=@($_.Triggers | Select-Object StartBoundary,Enabled,DaysOfWeek,WeeksInterval) } }
  $backupScript = Join-Path $installRoot 'resources/backend/_internal/scripts/backup/XcagiBackup.ps1'
  $dailyScriptArg = ([string]$daily.Actions[0].Arguments).Replace('/', '\')
  $weeklyScriptArg = ([string]$weekly.Actions[0].Arguments).Replace('/', '\')
  Check ($daily.Actions[0].Execute -match 'powershell.exe' -and $dailyScriptArg -match [regex]::Escape($backupScript.Replace('/', '\')) -and $dailyScriptArg -match '-NoProfile.*-NonInteractive.*-ExecutionPolicy Bypass' -and $weekly.Actions[0].Execute -match 'powershell.exe' -and $weeklyScriptArg -match [regex]::Escape($backupScript.Replace('/', '\')) -and $weeklyScriptArg -match '-NoProfile.*-NonInteractive.*-ExecutionPolicy Bypass') 'backup_task_action' 'daily and weekly task actions use noninteractive policy flags and the packaged backup script'
  $taskUser = ([string]$daily.Principal.UserId -split '\\')[-1]
  Check ($taskUser -eq $env:USERNAME -and $weekly.Principal.UserId -eq $daily.Principal.UserId -and $daily.Principal.LogonType -eq 'Interactive' -and $weekly.Principal.LogonType -eq 'Interactive' -and $daily.Principal.RunLevel -eq 'Limited' -and $weekly.Principal.RunLevel -eq 'Limited') 'backup_task_identity' "user=$taskUser; daily=$($daily.Principal.LogonType)/$($daily.Principal.RunLevel); weekly=$($weekly.Principal.LogonType)/$($weekly.Principal.RunLevel)"
  Check ($weekly.Triggers.Count -gt 0) 'backup_weekly_trigger' 'weekly trigger exists'
  $installRegistryPath = 'HKCU:\Software\XCAGI'
  $originalInstallPath = $null
  if (Test-Path $installRegistryPath) {
    $originalInstallPath = (Get-ItemProperty -Path $installRegistryPath -ErrorAction Stop).InstallPath
    if ($originalInstallPath) {
      Remove-ItemProperty -Path $installRegistryPath -Name InstallPath -ErrorAction Stop
    }
  }
  try {
    foreach ($taskName in @('XcagiDailyBackup', 'XcagiWeeklyBackup')) {
      $runThreshold = (Get-Date).AddSeconds(-2)
      Start-ScheduledTask -TaskName $taskName
      $deadline = (Get-Date).AddMinutes(2)
      do { Start-Sleep -Seconds 3; $task = Get-ScheduledTaskInfo -TaskName $taskName; $taskState = (Get-ScheduledTask -TaskName $taskName).State } while (($task.LastRunTime -lt $runThreshold -or $taskState -eq 'Running' -or $task.LastTaskResult -eq 267009) -and (Get-Date) -lt $deadline)
      Check ($task.LastRunTime -ge $runThreshold -and $task.LastTaskResult -eq 0) "${taskName}_run" "last_result=$($task.LastTaskResult); last_run=$($task.LastRunTime.ToUniversalTime().ToString('o'))"
      $produced = Get-ChildItem (Join-Path $dataRoot 'backups') -Filter 'xcagi-*.db' -File | Sort-Object LastWriteTime -Descending | Select-Object -First 1
      Check ($produced -and $produced.Length -gt 0 -and $produced.LastWriteTime -ge $runThreshold) "${taskName}_artifact" "bytes=$($produced.Length); sha256=$((Get-FileHash -LiteralPath $produced.FullName -Algorithm SHA256).Hash.ToLowerInvariant())"
    }
  } finally {
    if ($originalInstallPath) {
      Set-ItemProperty -Path $installRegistryPath -Name InstallPath -Value $originalInstallPath
    }
  }
  $backupLog = Join-Path $dataRoot 'logs/backup.log'
  $logTail = if (Test-Path $backupLog) { ((Get-Content $backupLog -Tail 8) -replace [regex]::Escape($env:USERPROFILE), '<USERPROFILE>') -join ' | ' } else { 'backup.log absent' }
  $packagedBackend = Join-Path $installRoot 'resources/backend/xcagi-backend.exe'
  $expectedBackendLog = $packagedBackend -replace [regex]::Escape($env:USERPROFILE), '<USERPROFILE>'
  Check ($logTail.Contains($expectedBackendLog)) 'backup_packaged_backend' 'scheduled task resolved the backend beside its packaged script without the registry install path'
  $backup = Get-ChildItem (Join-Path $dataRoot 'backups') -Filter 'xcagi-*.db' -File -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
  Check ($null -ne $backup -and $backup.Length -gt 0) 'backup_file' "bytes=$($backup.Length)"
  $restoreRoot = Join-Path $env:RUNNER_TEMP "xcagi-backup-restore-$Mode"
  Check (-not (Test-Path $restoreRoot)) 'backup_restore_isolated' 'restore destination is fresh'
  $restoreDataDir = Join-Path $restoreRoot 'data'
  New-Item -ItemType Directory -Force -Path $restoreDataDir | Out-Null
  $restoredDb = Join-Path $restoreDataDir 'xcagi.db'
  Copy-Item -LiteralPath $backup.FullName -Destination $restoredDb
  $backupSha = (Get-FileHash -LiteralPath $backup.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
  $restoredSha = (Get-FileHash -LiteralPath $restoredDb -Algorithm SHA256).Hash.ToLowerInvariant()
  Check ($backupSha -eq $restoredSha) 'backup_restore_copy' "sha256=$restoredSha; bytes=$((Get-Item $restoredDb).Length)"
  $previousUserData = $env:XCAGI_DESKTOP_USER_DATA_DIR
  try {
    Stop-App
    $env:XCAGI_DESKTOP_USER_DATA_DIR = $restoreRoot
    $restoredProcess = Start-App 'backup_restore'
    $restoredAuth = Login 'backup_restore'
    Check ($restoredAuth.tenant -eq $newAuth.tenant) 'backup_restore_enterprise' "tenant_sha256=$(Digest $restoredAuth.tenant)"
    Read-Record $restoredAuth.session $marker $marker 'backup_restore'
    if ($candidateGuiProof) { Run-Gui 'readback' (Join-Path $EvidenceDir 'restored-gui') $candidateGuiProof | Out-Null }
  } finally {
    $env:XCAGI_DESKTOP_USER_DATA_DIR = $previousUserData
    Stop-App
  }
}
function Run-Gui([string]$phase, [string]$directory, [string]$seed = '') {
  New-Item -ItemType Directory -Force -Path $directory | Out-Null
  $env:XCAGI_GUI_EVIDENCE = (Resolve-Path $directory).Path
  $env:XCAGI_GUI_PHASE = $phase
  $env:XCAGI_GUI_SEED = $seed
  & node (Join-Path $PSScriptRoot '../dev/record_enterprise_desktop_init.mjs')
  Check ($LASTEXITCODE -eq 0) "normal_gui_$phase" 'normal UI must save and read back actual business records'
  return (Join-Path $env:XCAGI_GUI_EVIDENCE 'gui-business.json')
}
try {
  Check (-not (Test-Path $dataRoot) -and -not (Test-Path $installRoot)) 'isolated_runner' 'fresh user data and install path'
  Check (-not (Get-ScheduledTask -TaskName XcagiDailyBackup -ErrorAction SilentlyContinue)) 'isolated_tasks' 'no prior daily task'
  $candidateHash = (Get-FileHash -LiteralPath $CandidatePath -Algorithm SHA256).Hash.ToLowerInvariant()
  $evidence.candidate_sha256 = $candidateHash
  if ($Mode -eq 'Gui') {
    Install $CandidatePath 'candidate'
    Start-App 'candidate'
    Run-Gui 'business' $EvidenceDir | Out-Null
    $evidence.result = 'gui_regression_passed'
    return
  }
  if ($Mode -eq 'Upgrade') {
    Check ((Get-FileHash -LiteralPath $OldPath -Algorithm SHA256).Hash.ToLowerInvariant() -eq $OldSha256) 'old_installer_hash' "sha256=$OldSha256"
    Install $OldPath 'old'
    $oldProcess = Start-App 'old'
    $oldGuiSeed = Run-Gui 'seed' (Join-Path $EvidenceDir 'old-gui')
    $oldAuth = Login 'old'
    $marker = "ACCEPT-UPGRADE-$env:GITHUB_RUN_ID-$env:GITHUB_RUN_ATTEMPT"
    $recordId = Create-Record $oldAuth.session $marker 'before_upgrade'
    Stop-App
    Install $CandidatePath 'candidate'
    $newProcess = Start-App 'candidate'
    $newAuth = Login 'candidate'
    Check ($newAuth.tenant -eq $oldAuth.tenant) 'same_enterprise' "tenant_sha256=$(Digest $newAuth.tenant)"
    Read-Record $newAuth.session $recordId $marker 'after_upgrade'
    $candidateGuiProof = Run-Gui 'after-upgrade' (Join-Path $EvidenceDir 'after-upgrade-gui') $oldGuiSeed
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
  $backendLog = Join-Path $dataRoot 'logs/electron-backend.log'
  if (Test-Path $backendLog) { Get-Content -LiteralPath $backendLog | Where-Object { $_ -notmatch '(?i)token|password|secret|authorization|cookie|username|[a-z0-9_-]{40,}' -and (-not $env:XCAGI_TEST_USER -or -not $_.Contains($env:XCAGI_TEST_USER)) -and (-not $env:XCAGI_TEST_PASS -or -not $_.Contains($env:XCAGI_TEST_PASS)) } | Set-Content (Join-Path $EvidenceDir 'backend-redacted.log') -Encoding utf8 }
  $evidence.finished_at = (Get-Date).ToUniversalTime().ToString('o')
  $evidence | ConvertTo-Json -Depth 8 | Set-Content (Join-Path $EvidenceDir 'acceptance.json') -Encoding utf8
  Stop-App
}
