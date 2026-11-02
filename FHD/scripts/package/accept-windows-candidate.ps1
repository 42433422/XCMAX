param(
  [Parameter(Mandatory=$true)][ValidateSet('Clean','Upgrade','Gui','Recovery','Rollback')][string]$Mode,
  [Parameter(Mandatory=$true)][string]$CandidatePath,
  [Parameter(Mandatory=$true)][string]$CandidateSha,
  [Parameter(Mandatory=$true)][string]$EvidenceDir,
  [string]$OldPath = '',
  [string]$BaselineVersion = ''
)
$ErrorActionPreference = 'Stop'; . (Join-Path $PSScriptRoot 'product-version.ps1'); $productVersion = Resolve-ProductVersion
$accountMode = if ($env:XCAGI_ACCEPTANCE_ACCOUNT_MODE) { $env:XCAGI_ACCEPTANCE_ACCOUNT_MODE } else { 'shared-serial' }
$baselines = (Get-Content (Join-Path $PSScriptRoot '../../config/download_release.json') -Raw | ConvertFrom-Json).windows_acceptance_baselines
if (-not $BaselineVersion) { $BaselineVersion = $baselines.default }
$baselineProperty = $baselines.PSObject.Properties[$BaselineVersion]
if (-not $baselineProperty -or $BaselineVersion -eq 'default' -or $BaselineVersion -eq '_doc') { throw 'Unknown frozen acceptance baseline' }
$baseline = $baselineProperty.Value; $OldSha = $baseline.git_sha; $OldSha256 = $baseline.sha256
$installRoot = Join-Path $env:RUNNER_TEMP "xcagi-candidate-$Mode"; $dataRoot = Join-Path $env:APPDATA 'XCAGI'; if ($Mode -in @('Upgrade','Rollback')) { $installRoot = Join-Path $env:LOCALAPPDATA 'Programs\XCAGI' }; $base = 'http://127.0.0.1:17500'; git merge-base --is-ancestor $CandidateSha origin/main
if ($LASTEXITCODE -gt 1) { throw 'Unable to verify candidate mainline ancestry' }
$evidence = [ordered]@{ mode=$Mode; candidate_sha=$CandidateSha; baseline_version=$BaselineVersion; baseline_sha=$OldSha; baseline_sha256=$OldSha256; candidate_on_main=($LASTEXITCODE -eq 0); customer_acceptance='not_verified'; started_at=(Get-Date).ToUniversalTime().ToString('o'); checks=@(); result='running' }; $global:LASTEXITCODE = 0; New-Item -ItemType Directory -Force -Path $EvidenceDir | Out-Null
function Check([bool]$ok, [string]$name, [string]$detail) {
  $script:evidence.checks += @{ name=$name; passed=$ok; detail=$detail }
  if (-not $ok) { throw "$name failed: $detail" }
}
function Digest([string]$text) {
  $bytes = [Text.Encoding]::UTF8.GetBytes($text); $hash = [Security.Cryptography.SHA256]::Create().ComputeHash($bytes); return ([BitConverter]::ToString($hash) -replace '-', '').ToLowerInvariant()
}
function Uninstall-OldApp {
  $unins = Get-ChildItem -LiteralPath $installRoot -Filter 'Uninstall*.exe' -File | Select-Object -First 1; Check ($null -ne $unins) 'old.uninstaller' 'previous uninstaller exists'
  $copied = Join-Path $env:TEMP 'xcagi-old-uninstaller.exe'; Copy-Item -LiteralPath $unins.FullName -Destination $copied -Force
  $psi = New-Object System.Diagnostics.ProcessStartInfo; $psi.FileName = $copied
  $psi.Arguments = "/S /KEEP_APP_DATA /currentuser _?=$installRoot"; $psi.UseShellExecute = $false
  $proc = [System.Diagnostics.Process]::Start($psi); $proc.WaitForExit()
  Check ($proc.ExitCode -eq 0) 'old.uninstall' "exit=$($proc.ExitCode)"
}
function Stop-App {
  Get-Process -Name XCAGI,xcagi-backend -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue; Start-Sleep -Seconds 2
}
function Install([string]$path, [string]$label) {
  $p = Start-Process -FilePath $path -ArgumentList @('/S',"/D=$installRoot") -Wait -PassThru; Check ($p.ExitCode -eq 0) "$label.install" "exit=$($p.ExitCode)"
  Check (Test-Path (Join-Path $installRoot 'XCAGI.exe')) "$label.exe" "installed executable exists; build_info=$(Get-Content (Join-Path $installRoot 'resources/build-info.json') -Raw)"
}
function Start-App([string]$label) {
  $launch = @{FilePath=(Join-Path $installRoot 'XCAGI.exe'); WorkingDirectory=$installRoot; PassThru=$true; WindowStyle='Hidden'}
  if ($Mode -in @('Gui','Upgrade','Recovery','Rollback')) { $launch.ArgumentList = @('--remote-debugging-port=9222') }
  $p = Start-Process @launch; $deadline = (Get-Date).AddMinutes(4)
  $health = $null; $status = $null
  while ((Get-Date) -lt $deadline) {
    $p.Refresh()
    if ($p.HasExited) { Check $false "$label.process" "pid=$($p.Id) exited before ready" }
    try {
      $health = Invoke-RestMethod "$base/api/health?lite=true" -TimeoutSec 3; $status = Invoke-RestMethod "$base/api/desktop/status" -TimeoutSec 3
      if ($health.status -ne 'unhealthy' -and @($health.runtime.blockers).Count -eq 0 -and $status.readyForUi -eq $true) { break }
    } catch { }
    Start-Sleep -Seconds 2
  }
  Check ($health.status -ne 'unhealthy' -and @($health.runtime.blockers).Count -eq 0 -and $status.readyForUi -eq $true) "$label.first_start_ready" "health=$($health.status); blockers=$(@($health.runtime.blockers).Count); readyForUi=$($status.readyForUi); pid=$($p.Id)"; $installed = Get-Content (Join-Path $installRoot 'resources/build-info.json') -Raw | ConvertFrom-Json
  Check (($label -eq 'old' -and $installed.gitSha -eq $OldSha -and ($installed.version -eq $BaselineVersion -and ($health.git_sha -eq $installed.gitSha -or ($baseline.allow_missing_health_identity -eq $true -and -not $health.git_sha)))) -or ($label -ne 'old' -and $installed.gitSha -eq $CandidateSha -and $health.git_sha -eq $CandidateSha)) "$label.runtime_build_identity" "installed=$($installed.gitSha); running=$($health.git_sha); legacy_health_identity_missing=$(-not $health.git_sha); release=$($health.release_id)"; $listener = Get-NetTCPConnection -LocalPort 17500 -State Listen -ErrorAction Stop | Select-Object -First 1
  $backend = Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)"; $dataArgument = [regex]::Match($backend.CommandLine, '--data-dir\s+(?:"([^"]+)"|(\S+))'); $actualDataRoot = if ($dataArgument.Groups[1].Success) { $dataArgument.Groups[1].Value } else { $dataArgument.Groups[2].Value }
  $expectedDataRoot = if ($env:XCAGI_DESKTOP_USER_DATA_DIR) { $env:XCAGI_DESKTOP_USER_DATA_DIR } else { $dataRoot }; Check (($backend.ExecutablePath -match ('^' + [regex]::Escape($installRoot + [IO.Path]::DirectorySeparatorChar))) -and $dataArgument.Success -and $actualDataRoot -eq $expectedDataRoot) "$label.port_owner" "pid=$($backend.ProcessId); exe=$($backend.ExecutablePath); actual_data=$actualDataRoot; expected_data=$expectedDataRoot"
  $p.Refresh(); Check (-not $p.HasExited) "$label.no_restart" "original pid=$($p.Id)"
}
function Login([string]$label) {
  Check ([bool]$env:XCAGI_TEST_USER -and [bool]$env:XCAGI_TEST_PASS) "$label.credentials" 'CI test credentials are configured'; $session = New-Object Microsoft.PowerShell.Commands.WebRequestSession
  $body = @{ username=$env:XCAGI_TEST_USER; password=$env:XCAGI_TEST_PASS } | ConvertTo-Json -Compress
  try {
    $r = Invoke-WebRequest "$base/api/auth/login" -Method Post -Body $body -ContentType 'application/json' -WebSession $session -TimeoutSec 30; $http = [int]$r.StatusCode
    $j = $r.Content | ConvertFrom-Json
  } catch {
    Check $false "$label.login" "http=$([int]$_.Exception.Response.StatusCode); error=$($_.Exception.GetType().Name)"
  }
  Check ($http -eq 200 -and $j.success -eq $true) "$label.login" "http=$http; success=$($j.success)"; $me = Invoke-RestMethod "$base/api/auth/me" -WebSession $session -TimeoutSec 15
  $identity = $me.data; $kind = [string]$identity.account_kind
  if (-not $kind) { $kind = [string]$identity.user.account_kind }
  $tenant = [string]$identity.tenant_id
  if (-not $tenant) { $tenant = [string]$identity.tenant.id }
  if (-not $tenant) { $tenant = [string]$identity.user.tenant_id }
  Check ($kind -eq 'enterprise' -and $tenant) "$label.enterprise" "kind=$kind; tenant_sha256=$(Digest $tenant)"
  if ($accountMode -eq 'isolated-parallel') {
    Check ($identity.market_is_enterprise -is [bool] -and $identity.market_is_enterprise -eq $true -and $identity.market_is_admin -is [bool] -and $identity.market_is_admin -eq $false -and $null -eq $identity.impersonating_market_user_id -and [string]$identity.market_user_id -ceq $env:XCAGI_TEST_MARKET_USER_ID) "$label.business_identity" 'dedicated cloud business identity matches the configured mode'
    $script:evidence.market_user_sha256 = Digest ([string]$identity.market_user_id)
  }
  return @{ session=$session; tenant=$tenant }
}
function Backup-And-Version {
  $infoPath = Join-Path $installRoot 'resources/build-info.json'; $info = Get-Content $infoPath -Raw | ConvertFrom-Json
  Check ($info.gitSha -eq $CandidateSha -and $info.version -eq $productVersion) 'build_info' "sha=$($info.gitSha); version=$($info.version)"; $display = @('HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*','HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*') | ForEach-Object { Get-ItemProperty $_ -ErrorAction SilentlyContinue } | Where-Object { $_.DisplayName -like 'XCAGI*' } | Select-Object -First 1
  Check ($display.DisplayVersion -eq $productVersion) 'installer_display_version' "display=$($display.DisplayVersion); expected=$productVersion"; $daily = Get-ScheduledTask -TaskName XcagiDailyBackup -ErrorAction Stop; $weekly = Get-ScheduledTask -TaskName XcagiWeeklyBackup -ErrorAction Stop
  $script:evidence.backup_tasks = @($daily, $weekly) | ForEach-Object { @{ name=$_.TaskName; user=$_.Principal.UserId; logon=[string]$_.Principal.LogonType; run_level=[string]$_.Principal.RunLevel; actions=@($_.Actions | Select-Object Execute,Arguments,WorkingDirectory); triggers=@($_.Triggers | Select-Object StartBoundary,Enabled,DaysOfWeek,WeeksInterval) } }; $backupScript = Join-Path $installRoot 'resources/backend/_internal/scripts/backup/XcagiBackup.ps1'; $dailyScriptArg = ([string]$daily.Actions[0].Arguments).Replace('/', '\'); $weeklyScriptArg = ([string]$weekly.Actions[0].Arguments).Replace('/', '\')
  Check ($daily.Actions[0].Execute -match 'powershell.exe' -and $dailyScriptArg -match [regex]::Escape($backupScript.Replace('/', '\')) -and $dailyScriptArg -match '-NoProfile.*-NonInteractive.*-ExecutionPolicy Bypass' -and $weekly.Actions[0].Execute -match 'powershell.exe' -and $weeklyScriptArg -match [regex]::Escape($backupScript.Replace('/', '\')) -and $weeklyScriptArg -match '-NoProfile.*-NonInteractive.*-ExecutionPolicy Bypass') 'backup_task_action' 'daily and weekly task actions use noninteractive policy flags and the packaged backup script'; $expectedBackupData = if ($env:XCAGI_DESKTOP_USER_DATA_DIR) { $env:XCAGI_DESKTOP_USER_DATA_DIR } else { $dataRoot }
  Check ($dailyScriptArg -match [regex]::Escape("-DataDir `"$expectedBackupData`"") -and $weeklyScriptArg -match [regex]::Escape("-DataDir `"$expectedBackupData`"") -and $weeklyScriptArg -match '-Weekly') 'backup_task_data_dir' "daily and weekly tasks target $expectedBackupData"; $taskUser = ([string]$daily.Principal.UserId -split '\\')[-1]
  Check ($taskUser -eq $env:USERNAME -and $weekly.Principal.UserId -eq $daily.Principal.UserId -and $daily.Principal.LogonType -eq 'Interactive' -and $weekly.Principal.LogonType -eq 'Interactive' -and $daily.Principal.RunLevel -eq 'Limited' -and $weekly.Principal.RunLevel -eq 'Limited') 'backup_task_identity' "user=$taskUser; daily=$($daily.Principal.LogonType)/$($daily.Principal.RunLevel); weekly=$($weekly.Principal.LogonType)/$($weekly.Principal.RunLevel)"; Check ($weekly.Triggers.Count -gt 0) 'backup_weekly_trigger' 'weekly trigger exists'
  $installRegistryPath = 'HKCU:\Software\XCAGI'; $originalInstallPath = $null
  if (Test-Path $installRegistryPath) {
    $originalInstallPath = (Get-ItemProperty -Path $installRegistryPath -ErrorAction Stop).InstallPath
    if ($originalInstallPath) {
      Remove-ItemProperty -Path $installRegistryPath -Name InstallPath -ErrorAction Stop
    }
  }
  try {
    foreach ($taskName in @('XcagiDailyBackup', 'XcagiWeeklyBackup')) {
      $runThreshold = (Get-Date).AddSeconds(-2); Start-ScheduledTask -TaskName $taskName
      $deadline = (Get-Date).AddMinutes(2); do { Start-Sleep -Seconds 3; $task = Get-ScheduledTaskInfo -TaskName $taskName; $taskState = (Get-ScheduledTask -TaskName $taskName).State } while (($task.LastRunTime -lt $runThreshold -or $taskState -eq 'Running' -or $task.LastTaskResult -eq 267009) -and (Get-Date) -lt $deadline)
      Check ($task.LastRunTime -ge $runThreshold -and $task.LastTaskResult -eq 0) "${taskName}_run" "last_result=$($task.LastTaskResult); last_run=$($task.LastRunTime.ToUniversalTime().ToString('o'))"; $produced = Get-ChildItem (Join-Path $dataRoot 'backups') -Filter 'xcagi-*.db' -File | Sort-Object LastWriteTime -Descending | Select-Object -First 1
      Check ($produced -and $produced.Length -gt 0 -and $produced.LastWriteTime -ge $runThreshold) "${taskName}_artifact" "bytes=$($produced.Length); sha256=$((Get-FileHash -LiteralPath $produced.FullName -Algorithm SHA256).Hash.ToLowerInvariant())"
    }
  } finally {
    if ($originalInstallPath) {
      Set-ItemProperty -Path $installRegistryPath -Name InstallPath -Value $originalInstallPath
    }
  }
  $backupLog = Join-Path $dataRoot 'logs/backup.log'; $logTail = if (Test-Path $backupLog) { ((Get-Content $backupLog -Tail 8) -replace [regex]::Escape($env:USERPROFILE), '<USERPROFILE>') -join ' | ' } else { 'backup.log absent' }; $packagedBackend = Join-Path $installRoot 'resources/backend/xcagi-backend.exe'; $expectedBackendLog = $packagedBackend -replace [regex]::Escape($env:USERPROFILE), '<USERPROFILE>'
  Check ($logTail.Contains($expectedBackendLog)) 'backup_packaged_backend' 'scheduled task resolved the backend beside its packaged script without the registry install path'; $backup = Get-ChildItem (Join-Path $dataRoot 'backups') -Filter 'xcagi-*.db' -File -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
  Check ($null -ne $backup -and $backup.Length -gt 0) 'backup_file' "bytes=$($backup.Length)"; $restoreRoot = Join-Path $env:RUNNER_TEMP "xcagi-backup-restore-$Mode"; Check (-not (Test-Path $restoreRoot)) 'backup_restore_isolated' 'restore destination is fresh'
  $restoreDataDir = Join-Path $restoreRoot 'data'; New-Item -ItemType Directory -Force -Path $restoreDataDir | Out-Null; $restoredDb = Join-Path $restoreDataDir 'xcagi.db'; Copy-Item -LiteralPath $backup.FullName -Destination $restoredDb
  $backupSha = (Get-FileHash -LiteralPath $backup.FullName -Algorithm SHA256).Hash.ToLowerInvariant(); $restoredSha = (Get-FileHash -LiteralPath $restoredDb -Algorithm SHA256).Hash.ToLowerInvariant()
  Check ($backupSha -eq $restoredSha) 'backup_restore_copy' "sha256=$restoredSha; bytes=$((Get-Item $restoredDb).Length)"; $previousUserData = $env:XCAGI_DESKTOP_USER_DATA_DIR
  try {
    Stop-App; $env:XCAGI_DESKTOP_USER_DATA_DIR = $restoreRoot
    $restoredProcess = Start-App 'backup_restore'; $restoredAuth = Login 'backup_restore'
    Check ($restoredAuth.tenant -eq $newAuth.tenant) 'backup_restore_enterprise' "tenant_sha256=$(Digest $restoredAuth.tenant)"
    if ($Mode -eq 'Upgrade') {
      & python (Join-Path $PSScriptRoot 'windows-lifecycle-fixtures.py') backup-verify $restoredDb $EvidenceDir
      Check ($LASTEXITCODE -eq 0) 'backup_restore.synthetic_rows' 'restored scheduled backup contains synthetic records and passes SQLite integrity'
    }
    if ($candidateGuiProof) { Run-Gui 'readback' (Join-Path $EvidenceDir 'restored-gui') $candidateGuiProof | Out-Null }
  } finally {
    $env:XCAGI_DESKTOP_USER_DATA_DIR = $previousUserData; Stop-App
  }
}
function Run-Gui([string]$phase, [string]$directory, [string]$seed = '') {
  New-Item -ItemType Directory -Force -Path $directory | Out-Null; $env:XCAGI_GUI_EVIDENCE = (Resolve-Path $directory).Path; $env:XCAGI_GUI_PHASE = $phase; $env:XCAGI_GUI_SEED = $seed
  $env:XCAGI_GUI_MODE = $Mode
  $env:XCAGI_GUI_BUILD_SHA = (Get-Content (Join-Path $installRoot 'resources/build-info.json') -Raw | ConvertFrom-Json).gitSha
  & node (Join-Path $PSScriptRoot '../dev/record_enterprise_desktop_init.mjs'); Check ($LASTEXITCODE -eq 0) "normal_gui_$phase" 'requested GUI phase must complete with all assertions'
  return (Join-Path $env:XCAGI_GUI_EVIDENCE 'gui-business.json')
}
function Fixture([string]$action) {
  & python (Join-Path $PSScriptRoot 'windows-lifecycle-fixtures.py') $action $dataRoot $EvidenceDir
  Check ($LASTEXITCODE -eq 0) "owned_state.$action" 'synthetic configuration, attachment, private SQLite rows and an actual 261-character path'
}
function Invoke-AppUpdate {
  & node (Join-Path $PSScriptRoot 'windows-lifecycle-update.mjs') install $EvidenceDir
  Check ($LASTEXITCODE -eq 0) 'app_update.download_and_handoff' 'original packaged app checked signature, downloaded candidate and invoked its own install IPC'
  Add-Type -AssemblyName UIAutomationClient; Add-Type -AssemblyName UIAutomationTypes
  $scope = [System.Windows.Automation.TreeScope]::Descendants
  $deadline = (Get-Date).AddMinutes(5); $window = $null
  do {
    foreach ($w in [System.Windows.Automation.AutomationElement]::RootElement.FindAll([System.Windows.Automation.TreeScope]::Children, [System.Windows.Automation.Condition]::TrueCondition)) {
      try {
        $proc = Get-Process -Id $w.Current.ProcessId -ErrorAction Stop
        if ($proc.Path -and (Get-FileHash -LiteralPath $proc.Path -Algorithm SHA256).Hash.ToLowerInvariant() -eq $candidateHash) { $window = $w; break }
      } catch {}
    }
    if (-not $window) { Start-Sleep -Seconds 2 }
  } while (-not $window -and (Get-Date) -lt $deadline)
  Check ($null -ne $window) 'app_update.installer_identity' 'updater launched the exact verified candidate executable'
  function Control([string]$id) { return $window.FindFirst($scope, [System.Windows.Automation.PropertyCondition]::new([System.Windows.Automation.AutomationElement]::AutomationIdProperty, $id)) }
  $deadline = (Get-Date).AddMinutes(1); do { $welcome = Control 'WelcomeAgreeCheck'; if (-not $welcome -or $welcome.Current.IsOffscreen) { Start-Sleep -Milliseconds 500 } } while ((-not $welcome -or $welcome.Current.IsOffscreen) -and (Get-Date) -lt $deadline)
  Check ($welcome -and -not $welcome.Current.IsOffscreen) 'app_update.installer_ready' 'verified candidate installer welcome page is visible'
  $agree = (Control 'WelcomeAgreeCheck').GetCurrentPattern([System.Windows.Automation.TogglePattern]::Pattern)
  if ($agree.Current.ToggleState -eq 'Off') { $agree.Toggle() }
  (Control 'NextButton').GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke(); Start-Sleep -Seconds 1
  $target = (Control 'InstallDirBox').GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern).Current.Value
  Check ($target -eq $installRoot) 'app_update.install_target' "target=$target"
  $run = (Control 'RunAfterInstallCheck').GetCurrentPattern([System.Windows.Automation.TogglePattern]::Pattern)
  if ($run.Current.ToggleState -eq 'On') { $run.Toggle() }
  (Control 'NextButton').GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke()
  $deadline = (Get-Date).AddMinutes(15)
  do {
    Start-Sleep -Seconds 2; $errorText = Control 'ErrorMessageText'; $complete = Control 'CompletePathText'
    if ($errorText -and -not $errorText.Current.IsOffscreen) { throw "App updater installer failed: $($errorText.Current.Name)" }
  } while ((-not $complete -or $complete.Current.IsOffscreen) -and (Get-Date) -lt $deadline)
  Check ($complete -and -not $complete.Current.IsOffscreen) 'app_update.install_completed' 'real updater-launched installer finished without manual uninstall'
  (Control 'NextButton').GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke()
  $installed = Get-Content (Join-Path $installRoot 'resources/build-info.json') -Raw | ConvertFrom-Json
  Check ($installed.gitSha -eq $CandidateSha -and $installed.version -eq $productVersion) 'app_update.candidate_build' "sha=$($installed.gitSha); version=$($installed.version)"
  $markerPath = Join-Path $dataRoot 'rollback-marker.json'
  Check (Test-Path -LiteralPath $markerPath) 'app_update.natural_marker' 'application/installer produced rollback marker; harness never writes rollback state'
  $script:naturalMarker = Get-Content -LiteralPath $markerPath -Raw | ConvertFrom-Json
  Copy-Item -LiteralPath $markerPath -Destination (Join-Path $EvidenceDir 'natural-rollback-marker.json')
  # The installer replaces the Electron handoff with product versions and full build SHAs.
  $expectedFromVersion = "$BaselineVersion+$OldSha"
  $expectedToVersion = "$productVersion+$CandidateSha"
  Check ($naturalMarker.fromVersion -ceq $expectedFromVersion -and $naturalMarker.toVersion -ceq $expectedToVersion -and $naturalMarker.mode -eq 'windows-full') 'app_update.snapshot_identity' "from=$($naturalMarker.fromVersion); to=$($naturalMarker.toVersion)"
  foreach ($fixture in (Get-Content (Join-Path $EvidenceDir 'owned-fixtures.json') -Raw | ConvertFrom-Json)) {
    $entry = $naturalMarker.expectedOwnedFiles.PSObject.Properties[$fixture.path]
    Check ($entry -and $entry.Value -eq $fixture.sha256) 'app_update.owned_manifest' "path=$($fixture.path); length=$($fixture.absolute_length)"
    Check ((Get-FileHash -LiteralPath (Join-Path $naturalMarker.ownedBackupRoot $fixture.path) -Algorithm SHA256).Hash.ToLowerInvariant() -eq $fixture.sha256) 'app_update.owned_backup_hash' "sha256=$($fixture.sha256)"
  }
  $script:databaseBefore = (Get-FileHash -LiteralPath $naturalMarker.databaseBackupPath -Algorithm SHA256).Hash.ToLowerInvariant()
  & python (Join-Path $PSScriptRoot 'windows-lifecycle-fixtures.py') backup-verify $naturalMarker.databaseBackupPath $EvidenceDir
  Check ($LASTEXITCODE -eq 0) 'app_update.synthetic_backup_rows' 'natural backup contains synthetic records and passes SQLite integrity'
  Check ((Get-FileHash -LiteralPath (Join-Path $dataRoot 'data/xcagi.db') -Algorithm SHA256).Hash.ToLowerInvariant() -eq $databaseBefore) 'app_update.natural_database_backup' "sha256=$databaseBefore"
}
function Assert-RollbackEvidence {
  $appliedPath = Join-Path $dataRoot 'rollback-applied.last.json'
  try {
    Check (Test-Path -LiteralPath $appliedPath -PathType Leaf) 'rollback.applied_record' 'persistent automatic rollback receipt exists'
    try { $applied = Get-Content -LiteralPath $appliedPath -Raw | ConvertFrom-Json } catch { Check $false 'rollback.applied_record' 'persistent receipt is unreadable' }
    $restored = Get-Content (Join-Path $installRoot 'resources/build-info.json') -Raw | ConvertFrom-Json
    Check ($restored.gitSha -eq $OldSha -and $restored.version -eq $BaselineVersion -and -not (Test-Path (Join-Path $dataRoot 'rollback-marker.json'))) 'rollback.restored_build' 'original build restored and natural pending marker consumed'
    Check ((Get-FileHash -LiteralPath $db -Algorithm SHA256).Hash.ToLowerInvariant() -eq $databaseBefore) 'rollback.database_hash' "sha256=$databaseBefore"
    $validTimes = $false
    try { $appliedAt = [DateTimeOffset]$applied.appliedAt; $completedAt = [DateTimeOffset]$applied.completedAt; $validTimes = $true } catch {}
    Check ($validTimes -and $applied.operationId -and (-not $naturalMarker.operationId -or $applied.operationId -eq $naturalMarker.operationId) -and $applied.reason -and $applied.fromVersion -eq $naturalMarker.toVersion -and $applied.toVersion -eq $naturalMarker.fromVersion -and $appliedAt -ge [DateTimeOffset]$naturalMarker.preparedAt -and $completedAt -ge $appliedAt -and $completedAt -le [DateTimeOffset]::UtcNow) 'rollback.applied_record' "operation=$($applied.operationId); from=$($applied.fromVersion); to=$($applied.toVersion); completed=$($applied.completedAt)"
  } finally {
    if ($appliedPath -and (Test-Path -LiteralPath $appliedPath -PathType Leaf)) { Copy-Item -LiteralPath $appliedPath -Destination (Join-Path $EvidenceDir 'rollback-applied.last.json') -Force }
  }
}
function Invoke-FailedRollback([string]$tenant) {
  Fixture 'dirty'
  $db = Join-Path $dataRoot 'data/xcagi.db'; Check ((Get-FileHash -LiteralPath $db -Algorithm SHA256).Hash.ToLowerInvariant() -ne $databaseBefore) 'rollback.database_changed' 'controlled isolated database write differs from natural snapshot'
  $listener = [System.Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, 17500); $listener.Start()
  try {
    Start-Process -FilePath (Join-Path $installRoot 'XCAGI.exe') -WorkingDirectory $installRoot | Out-Null
    $deadline = (Get-Date).AddMinutes(5); $appliedPath = Join-Path $dataRoot 'rollback-applied.last.json'; $applied = $null
    do {
      Start-Sleep -Seconds 2
      if (Test-Path -LiteralPath $appliedPath) { try { $applied = Get-Content -LiteralPath $appliedPath -Raw | ConvertFrom-Json } catch {} }
    } while (($applied.fromVersion -ne $naturalMarker.toVersion -or $applied.toVersion -ne $naturalMarker.fromVersion -or -not $applied.completedAt) -and (Get-Date) -lt $deadline)
    Assert-RollbackEvidence
    Fixture 'verify'
    & python (Join-Path $PSScriptRoot 'windows-lifecycle-fixtures.py') app-verify $installRoot $EvidenceDir
    Check ($LASTEXITCODE -eq 0) 'rollback.app_file_hashes' 'all original app files restored with no extra files'
  } finally { $listener.Stop() }
  Stop-App; Start-App 'old'; Run-Gui 'identity' (Join-Path $EvidenceDir 'rollback-gui') | Out-Null; Fixture 'main-verify'
  $back = Login 'old'; Check ($back.tenant -eq $tenant) 'rollback.same_enterprise' "tenant_sha256=$(Digest $back.tenant)"
}

try {
  Check ($accountMode -in @('shared-serial','isolated-parallel') -and ($accountMode -ne 'isolated-parallel' -or $env:XCAGI_TEST_MARKET_USER_ID -cmatch '^[1-9]\d*$')) 'account_configuration' 'explicit serial compatibility or pinned parallel identity'
  $evidence.account_mode = $accountMode; $evidence.account_sha256 = Digest $env:XCAGI_TEST_USER
  Check (-not (Test-Path $dataRoot) -and -not (Test-Path $installRoot)) 'isolated_runner' 'fresh user data and install path'; Check (-not (Get-ScheduledTask -TaskName XcagiDailyBackup -ErrorAction SilentlyContinue)) 'isolated_tasks' 'no prior daily task'
  $candidateHash = (Get-FileHash -LiteralPath $CandidatePath -Algorithm SHA256).Hash.ToLowerInvariant(); $evidence.candidate_sha256 = $candidateHash
  if ($Mode -in @('Gui','Recovery')) {
    Install $CandidatePath 'candidate'; Start-App 'candidate'
    $phase = if ($Mode -eq 'Recovery') { 'faults' } else { 'business' }; $candidateGuiProof = Run-Gui $phase $EvidenceDir
    if ($Mode -eq 'Recovery') { $newAuth = Login 'candidate'; Backup-And-Version }
    $evidence.result = if ($Mode -eq 'Recovery') { 'gui_recovery_regression_passed' } else { 'gui_regression_passed' }; return
  }
  if ($Mode -in @('Upgrade','Rollback')) {
    Check ((Get-FileHash -LiteralPath $OldPath -Algorithm SHA256).Hash.ToLowerInvariant() -eq $OldSha256) 'old_installer_hash' "sha256=$OldSha256"; Install $OldPath 'old'
    & python (Join-Path $PSScriptRoot 'windows-lifecycle-fixtures.py') app-seed $installRoot $EvidenceDir
    Check ($LASTEXITCODE -eq 0) 'old.app_file_hashes' 'full original installed app manifest recorded'
    Fixture 'seed'
    $env:XCAGI_UPDATE_URL = 'http://127.0.0.1:18765/'
    $feed = Start-Process node -ArgumentList @((Join-Path $PSScriptRoot 'windows-lifecycle-update.mjs'), 'serve', (Split-Path $CandidatePath), $CandidatePath) -PassThru -NoNewWindow
    Start-App 'old'; Stop-App; Fixture 'main-seed'; Start-App 'old'; Run-Gui 'identity' (Join-Path $EvidenceDir 'old-gui') | Out-Null; $oldAuth = Login 'old'
    Invoke-AppUpdate
    if ($Mode -eq 'Rollback') {
      Invoke-FailedRollback $oldAuth.tenant; $evidence.result = 'rollback_passed'; return
    }
    Start-App 'candidate'; $newAuth = Login 'candidate'
    $deadline = (Get-Date).AddMinutes(1); while ((Test-Path (Join-Path $dataRoot 'rollback-marker.json')) -and (Get-Date) -lt $deadline) { Start-Sleep -Seconds 2; $health = Invoke-RestMethod "$base/api/health?lite=true" -TimeoutSec 3; Check ($health.git_sha -eq $CandidateSha -and $health.status -ne 'unhealthy') 'upgrade.observation_identity' 'candidate remains healthy during natural commit observation' }
    Check (-not (Test-Path (Join-Path $dataRoot 'rollback-marker.json'))) 'upgrade.health_commit' 'candidate naturally committed its healthy-start observation'
    Check ($newAuth.tenant -eq $oldAuth.tenant) 'same_enterprise' "tenant_sha256=$(Digest $newAuth.tenant)"
    Run-Gui 'identity' (Join-Path $EvidenceDir 'after-upgrade-gui') | Out-Null; Fixture 'verify'; Fixture 'main-verify'
    Stop-App; Uninstall-OldApp
    Check (-not (Test-Path (Join-Path $installRoot 'XCAGI.exe'))) 'retention.uninstalled' 'candidate executable removed'
    Fixture 'verify'; Fixture 'main-verify'; Install $CandidatePath 'candidate'; Start-App 'candidate'
    Run-Gui 'identity' (Join-Path $EvidenceDir 'reinstalled-gui') | Out-Null; Fixture 'verify'; Fixture 'main-verify'
  } else {
    Install $CandidatePath 'candidate'; Start-App 'candidate'; $newAuth = Login 'candidate'
  }
  Backup-And-Version; $evidence.result = 'passed'
} catch {
  $evidence.result = 'failed'; $evidence.failure = $_.Exception.Message
  throw
} finally {
  if ($feed -and -not $feed.HasExited) { Stop-Process -Id $feed.Id -ErrorAction SilentlyContinue }; Remove-Item Env:XCAGI_UPDATE_URL -ErrorAction SilentlyContinue
  $evidence.runner = @{ os=[Environment]::OSVersion.VersionString; caption=(Get-CimInstance Win32_OperatingSystem).Caption; customer_windows_10_11='not_verified'; uac_interactive_consent='not_verified'; long_paths_policy=(Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem').LongPathsEnabled }
  $evidence.record_fixture_scope = 'dedicated synthetic SQLite records, not customer data or business UI acceptance'
  $evidence.mod_fixture_scope = 'synthetic owned configuration/attachment/private database retention; registered Mod loading and entitlement not verified'
  foreach ($log in @((Join-Path $env:TEMP 'xcagi-installer-silent.log'), (Join-Path $dataRoot 'rollback/rollback-helper.log'))) { if (Test-Path -LiteralPath $log) { Copy-Item -LiteralPath $log -Destination $EvidenceDir } }
  $backendLog = Join-Path $dataRoot 'logs/electron-backend.log'
  if (Test-Path $backendLog) { Get-Content -LiteralPath $backendLog | Where-Object { $_ -notmatch '(?i)token|password|secret|authorization|cookie|username|[a-z0-9_-]{40,}' -and (-not $env:XCAGI_TEST_USER -or -not $_.Contains($env:XCAGI_TEST_USER)) -and (-not $env:XCAGI_TEST_PASS -or -not $_.Contains($env:XCAGI_TEST_PASS)) } | Set-Content (Join-Path $EvidenceDir 'backend-redacted.log') -Encoding utf8 }
  $evidence.finished_at = (Get-Date).ToUniversalTime().ToString('o'); $evidence | ConvertTo-Json -Depth 8 | Set-Content (Join-Path $EvidenceDir 'acceptance.json') -Encoding utf8
  Stop-App
}
