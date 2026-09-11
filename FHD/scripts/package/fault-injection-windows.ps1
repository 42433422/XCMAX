<#
XCAGI 桌面端 Windows 故障注入验收（目标项 7 数据与并发安全 / 项 8 故障恢复与回退）
协议：docs/e2e/desktop-real-machine-acceptance-protocol.md

用途：对**验收隔离环境**注入运行时故障，取证端到端恢复行为。补齐
tests/test_desktop_db_resilience.py（函数级单测）之上的进程级/实机级证据。

场景：
  1. kill-all          运行中强杀全部进程（等价「强杀/断电对进程的影响」）→ 重启 → health + 数据无损。
  2. kill-orphan       模拟「孤儿后端」：主进程死了但 xcagi-backend.exe 仍占 17500 → 再启动 → 观察端口占用处理。
  3. corrupt-backup    损坏最新备份（不碰主库）→ 启动 → 坏备份不误伤正常启动。
  4. corrupt-main      损坏主库 → 启动 → 自动改名留证 + 从最近有效备份恢复 → health + 数据可访问。
                        ⚠ 仅允许在 C:\XCAGI-acceptance 隔离安装上执行，检测到其他安装根一律拒绝。
  人工场景（脚本给指引，不自动执行）：
  5. disk-full         磁盘写满（需卷配额/小 VHD，物理环境执行）。
  6. power-cut         异常断电（拔电/断 PDU，物理环境执行）。

行为依据：
  - recover_if_corrupt（app/desktop_runtime/migrate.py）：损坏库改名 .corrupt-{timestamp} 留证；
    按 backups/ 时间倒序找第一个通过 integrity_check 的备份恢复。
  - WAL + synchronous=FULL + wal_autocheckpoint=1000（app/db/__init__.py）：
    强杀/断电后已提交事务不丢，主库不应损坏。
  - 单实例锁 + 17500 端口（desktop/main.ts、backend-process.ts）。

用法示例：
  # 全部可自动化场景（默认对 C:\XCAGI-acceptance 隔离安装）
  .\scripts\package\fault-injection-windows.ps1
  # 只跑强杀与坏备份
  .\scripts\package\fault-injection-windows.ps1 -Scenario kill-all,corrupt-backup
  # 指定安装根与数据根（覆盖升级验收后的环境可直接复用）
  .\scripts\package\fault-injection-windows.ps1 -Scenario all -InstallRoot "C:\XCAGI-acceptance" -DataRoot "$env:APPDATA\XCAGI"
#>
param(
  [ValidateSet('all', 'kill-all', 'kill-orphan', 'corrupt-backup', 'corrupt-main')]
  [string[]]$Scenario = @('all'),
  # 安装根；默认按 C:\XCAGI-acceptance → %LOCALAPPDATA%\Programs\XCAGI → %ProgramFiles%\XCAGI 探测。
  [string]$InstallRoot = "",
  # 业务数据根目录；默认 %APPDATA%\XCAGI（与 desktop/main.ts userData 一致）。
  [string]$DataRoot = "",
  # 证据目录；默认 .\fault-injection-evidence-<时间戳>。
  [string]$EvidenceDir = "",
  # 健康检查地址（与验收脚本一致）。
  [string]$HealthUrl = 'http://127.0.0.1:17500/api/health',
  # CI/非交互模式：跳过人工场景 Read-Host 录入（disk-full/power-cut 记 SKIP），供 runner 执行。
  [switch]$CiMode
)

$ErrorActionPreference = 'Stop'
try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch { }
$AcceptRoot = 'C:\XCAGI-acceptance'
$script:Results = New-Object System.Collections.Generic.List[object]
$script:Timestamp = Get-Date -Format 'yyyyMMdd-HHmmss'

function Write-Step([string]$Name) {
  Write-Host ""
  Write-Host ("=" * 72) -ForegroundColor DarkCyan
  Write-Host ("FAULT {0}" -f $Name) -ForegroundColor Cyan
  Write-Host ("=" * 72) -ForegroundColor DarkCyan
}
function Write-Ok([string]$Msg)   { Write-Host ("  [OK]   " + $Msg) -ForegroundColor Green }
function Write-Warn2([string]$Msg){ Write-Host ("  [WARN] " + $Msg) -ForegroundColor Yellow }
function Write-Fail([string]$Msg) { Write-Host ("  [FAIL] " + $Msg) -ForegroundColor Red }
function Write-Info([string]$Msg) { Write-Host ("  [INFO] " + $Msg) -ForegroundColor Gray }

function Record([string]$Step, [string]$Result, [string]$Detail) {
  $script:Results.Add([PSCustomObject]@{ 场景 = $Step; 结果 = $Result; 说明 = $Detail })
  if ($Result -eq 'FAIL') { Write-Fail ("场景 [{0}] 记录为 FAIL：{1}" -f $Step, $Detail) }
}

# 等待 17500 端口释放（强杀后 sidecar/主进程退出需要时间）。
function Wait-PortFree([int]$Seconds = 30) {
  for ($i = 0; $i -lt $Seconds; $i++) {
    $conn = Get-NetTCPConnection -LocalPort 17500 -State Listen -ErrorAction SilentlyContinue
    if (-not $conn) { return $true }
    Start-Sleep -Seconds 1
  }
  return $false
}

# 启动应用并等 health；返回 $true=healthy。
function Start-App([string]$Exe) {
  Start-Process -FilePath $Exe | Out-Null
  for ($i = 0; $i -lt 90; $i++) {
    Start-Sleep -Seconds 1
    try {
      $health = Invoke-RestMethod -Uri $HealthUrl -TimeoutSec 3
      if ($health.status -eq 'healthy') { return $true }
    } catch { }
  }
  return $false
}

# 强杀全部 XCAGI 相关进程（Electron 主进程 + sidecar 后端）。
function Stop-AppAll {
  foreach ($name in @('XCAGI', 'xcagi-backend')) {
    Get-Process -Name $name -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
  }
  Start-Sleep -Seconds 2
  $freed = Wait-PortFree 30
  if (-not $freed) { Write-Warn2 "强杀后 17500 端口 30 秒内未释放（可能有残留进程）" }
  return $freed
}

# 业务数据快照（与 acceptance-windows.ps1 Get-BusinessDataDigest 同口径的关键字段）。
function Get-Digest([string]$Root) {
  $d = [ordered]@{}
  $mainDb = Join-Path $Root 'data\xcagi.db'
  $d['xcagi.db.bytes'] = if (Test-Path $mainDb) { (Get-Item $mainDb).Length } else { -1 }
  $vecDb = Join-Path $Root 'data\excel_vectors.db'
  $d['excel_vectors.db.bytes'] = if (Test-Path $vecDb) { (Get-Item $vecDb).Length } else { -1 }
  foreach ($sub in @('uploads', 'mods')) {
    $p = Join-Path $Root $sub
    $d["$sub.files"] = if (Test-Path $p) { @(Get-ChildItem $p -File -Recurse -ErrorAction SilentlyContinue).Count } else { 0 }
  }
  $bks = @(Get-ChildItem (Join-Path $Root 'backups') -File -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -match '^xcagi-.+?(-\w+)?-\d{14}\.db$' })
  $d['backups.files'] = $bks.Count
  $d['backups.latest'] = if ($bks.Count) { ($bks | Sort-Object LastWriteTime -Descending | Select-Object -First 1).Name } else { '' }
  $corrupt = @(Get-ChildItem (Join-Path $Root 'data') -Filter 'xcagi.db.corrupt-*' -File -ErrorAction SilentlyContinue)
  $d['corrupt.evidence'] = $corrupt.Count
  return $d
}

function Format-Digest([object]$Digest) {
  return (($Digest.Keys | ForEach-Object { "{0}={1}" -f $_, $Digest[$_] }) -join ' ')
}

function New-Evidence([string]$Name, [string]$Text) {
  $path = Join-Path $script:EvidenceDir ("{0}-{1}.txt" -f $Name, $script:Timestamp)
  Set-Content -Path $path -Value $Text -Encoding UTF8
  Write-Info ("证据已保存：{0}" -f $path)
  return $path
}

# ---------------------------------------------------------------- 前置检查
Write-Host ""
Write-Host "XCAGI 桌面端 Windows 故障注入验收（协议：docs/e2e/desktop-real-machine-acceptance-protocol.md）" -ForegroundColor White
if (-not $DataRoot) { $DataRoot = Join-Path $env:APPDATA 'XCAGI' }
if (-not $EvidenceDir) { $EvidenceDir = Join-Path (Get-Location) ("fault-injection-evidence-" + $script:Timestamp) }
New-Item -ItemType Directory -Force -Path $EvidenceDir | Out-Null
Write-Host ("证据目录：{0}" -f $EvidenceDir)
Write-Host ("数据根：{0}" -f $DataRoot)

if (-not $InstallRoot) {
  foreach ($c in @($AcceptRoot, (Join-Path $env:LOCALAPPDATA 'Programs\XCAGI'), (Join-Path ${env:ProgramFiles} 'XCAGI'))) {
    if (Test-Path (Join-Path $c 'resources\build-info.json')) { $InstallRoot = $c; break }
  }
}
if (-not ($InstallRoot -and (Test-Path (Join-Path $InstallRoot 'XCAGI.exe')))) {
  Write-Fail ("未找到可用的 XCAGI.exe（InstallRoot={0}）。请先完成 acceptance-windows.ps1 安装验收。" -f $InstallRoot)
  exit 1
}
Write-Ok ("安装根：{0}" -f $InstallRoot)
$AppExe = Join-Path $InstallRoot 'XCAGI.exe'
$BackendExe = Join-Path $InstallRoot 'resources\backend\xcagi-backend.exe'

$running = Get-Process -Name 'XCAGI' -ErrorAction SilentlyContinue
if ($running) {
  Write-Info "检测到运行中的 XCAGI 实例，故障注入需要先退出（强杀会污染前置状态）。"
  Stop-AppAll | Out-Null
}

if ($Scenario -contains 'all') { $Scenario = @('kill-all', 'kill-orphan', 'corrupt-backup', 'corrupt-main') }

# ---------------------------------------------------------------- 场景 1 kill-all
if ($Scenario -contains 'kill-all') {
  Write-Step "1/4 kill-all 强杀全部进程 → 重启恢复"
  if (-not (Start-App $AppExe)) {
    Record 'kill-all' 'FAIL' '前置启动失败（health 未 healthy），无法执行强杀场景'
  } else {
    $before = Get-Digest $DataRoot
    Write-Info ("强杀前快照：{0}" -f (Format-Digest $before))
    New-Evidence 'kill-all-before' (Format-Digest $before) | Out-Null
    Write-Info "注入：Stop-Process -Force（XCAGI + xcagi-backend，等价强杀/断电对进程的影响）"
    Stop-AppAll | Out-Null
    Write-Info "重启并等待 health ..."
    $healthy = Start-App $AppExe
    $after = Get-Digest $DataRoot
    New-Evidence 'kill-all-after' (Format-Digest $after) | Out-Null
    if (-not $healthy) {
      Record 'kill-all' 'FAIL' '强杀后重启 health 未恢复'
    } elseif ([int64]$after['xcagi.db.bytes'] -lt [int64]$before['xcagi.db.bytes']) {
      Record 'kill-all' 'FAIL' ("强杀后主库变小（{0} → {1}），疑似数据丢失" -f $before['xcagi.db.bytes'], $after['xcagi.db.bytes'])
    } elseif ([int64]$after['corrupt.evidence'] -gt 0) {
      Record 'kill-all' 'FAIL' '强杀后重启出现损坏库留证（WAL+synchronous=FULL 下不应发生）'
    } else {
      Write-Ok "强杀后重启：health healthy，主库无损坏证据，数据未减少"
      Record 'kill-all' 'PASS' ("health=healthy；主库 {0} → {1} 字节；corrupt 证据=0" -f $before['xcagi.db.bytes'], $after['xcagi.db.bytes'])
    }
    Stop-AppAll | Out-Null
  }
}

# ---------------------------------------------------------------- 场景 2 kill-orphan
if ($Scenario -contains 'kill-orphan') {
  Write-Step "2/4 kill-orphan 孤儿后端占端口 → 再启动"
  if (-not (Test-Path $BackendExe)) {
    Record 'kill-orphan' 'SKIP' ("未找到 sidecar：{0}" -f $BackendExe)
  } elseif (-not (Wait-PortFree 5)) {
    Record 'kill-orphan' 'FAIL' '17500 已被占用，前置不满足（先清场）'
  } else {
    Write-Info "注入：手动拉起 xcagi-backend.exe（模拟主进程死亡后遗留的孤儿后端），随后启动 XCAGI.exe"
    # 归档上次运行可能遗留的回滚证据，避免误判为本次触发。
    $rollback = Join-Path $DataRoot 'rollback-applied.json'
    if (Test-Path $rollback) { Move-Item $rollback ($rollback + '.prev') -Force }
    Start-Process -FilePath $BackendExe | Out-Null
    Start-Sleep -Seconds 6
    $orphanConn = Get-NetTCPConnection -LocalPort 17500 -State Listen -ErrorAction SilentlyContinue
    if (-not $orphanConn) { Write-Warn2 "孤儿后端未在 17500 监听（可能启动失败），场景按实际情况记录" }
    Start-Process -FilePath $AppExe | Out-Null
    Start-Sleep -Seconds 12
    $healthy = $false
    try { $h = Invoke-RestMethod -Uri $HealthUrl -TimeoutSec 3; if ($h.status -eq 'healthy') { $healthy = $true } } catch { }
    $rollbackNote = if (Test-Path $rollback) { (Get-Content $rollback -Raw -Encoding UTF8) } else { '' }
    New-Evidence 'kill-orphan' ("healthy={0}; rollback_applied={1}" -f $healthy, $rollbackNote) | Out-Null
    if ($healthy) {
      Write-Ok "孤儿后端场景：应用最终 health healthy（端口占用被妥善处理）"
      Record 'kill-orphan' 'PASS' '孤儿 sidecar 占端口后重启，最终 health healthy'
    } elseif ($rollbackNote) {
      Write-Warn2 "触发回滚保护（rollback-applied.json 已落盘），应用进入受控恢复路径"
      Record 'kill-orphan' 'PARTIAL' 'health 未恢复但回滚保护触发（受控行为，需人工复核原因）'
    } else {
      Record 'kill-orphan' 'FAIL' '孤儿后端占端口后应用既未恢复健康也无回滚证据'
    }
    Stop-AppAll | Out-Null
  }
}

# ---------------------------------------------------------------- 场景 3 corrupt-backup
if ($Scenario -contains 'corrupt-backup') {
  Write-Step "3/4 corrupt-backup 损坏最新备份 → 启动不受影响"
  $backupsDir = Join-Path $DataRoot 'backups'
  $bks = @(Get-ChildItem $backupsDir -File -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -match '^xcagi-.+?(-\w+)?-\d{14}\.db$' } | Sort-Object LastWriteTime -Descending)
  if (-not ($bks.Count -gt 0)) {
    Write-Info "无可用备份：先启动一次应用让迁移/备份产生，再退出。"
    if (Start-App $AppExe) { Stop-AppAll | Out-Null }
    $bks = @(Get-ChildItem $backupsDir -File -ErrorAction SilentlyContinue |
      Where-Object { $_.Name -match '^xcagi-.+?(-\w+)?-\d{14}\.db$' } | Sort-Object LastWriteTime -Descending)
  }
  if (-not ($bks.Count -gt 0)) {
    Record 'corrupt-backup' 'SKIP' '数据根无备份文件，场景无法执行'
  } else {
    $victim = $bks[0]
    $victimPath = $victim.FullName
    Copy-Item $victimPath ($victimPath + '.pre-inject') -Force
    Write-Info ("注入：向最新备份写入垃圾字节（不碰主库）：{0}" -f $victim.Name)
    [IO.File]::WriteAllBytes($victimPath, ([byte[]](0x58, 0x43, 0x41, 0x47, 0x49, 0x2D, 0x43, 0x4F, 0x52, 0x52, 0x55, 0x50, 0x54)))
    $beforeMain = (Get-Item (Join-Path $DataRoot 'data\xcagi.db')).Length
    $healthy = Start-App $AppExe
    $after = Get-Digest $DataRoot
    New-Evidence 'corrupt-backup' ("healthy={0}; victim={1}; main={2}→{3}" -f $healthy, $victim.Name, $beforeMain, $after['xcagi.db.bytes']) | Out-Null
    if ($healthy) {
      Write-Ok "坏备份未误伤正常启动（recover_if_corrupt 只在主库损坏时启用）"
      Record 'corrupt-backup' 'PASS' ("坏备份 {0} 存在时启动正常，主库未动" -f $victim.Name)
    } else {
      Record 'corrupt-backup' 'FAIL' '损坏备份后启动失败（坏备份不应影响健康主库的启动）'
    }
    Stop-AppAll | Out-Null
    Remove-Item ($victimPath + '.pre-inject') -ErrorAction SilentlyContinue
  }
}

# ---------------------------------------------------------------- 场景 4 corrupt-main
if ($Scenario -contains 'corrupt-main') {
  Write-Step "4/4 corrupt-main 损坏主库 → 自动恢复"
  # 安全闸：仅允许隔离验收目录，防止误伤客户真实安装。
  $isolated = ($InstallRoot -eq $AcceptRoot) -or ($InstallRoot.StartsWith($AcceptRoot + '\'))
  if (-not $isolated) {
    Write-Fail ("安全闸：InstallRoot={0} 不是隔离验收目录（{1}）。损坏主库只允许在隔离环境执行。" -f $InstallRoot, $AcceptRoot)
    Record 'corrupt-main' 'SKIP' ("安全闸拒绝：非隔离安装根 {0}" -f $InstallRoot)
  } else {
    $mainDb = Join-Path $DataRoot 'data\xcagi.db'
    if (-not (Test-Path $mainDb)) { Record 'corrupt-main' 'FAIL' ("主库不存在：{0}" -f $mainDb) }
    else {
      $before = Get-Digest $DataRoot
      if ([int64]$before['backups.files'] -le 0) {
        Record 'corrupt-main' 'SKIP' '无备份可恢复（corrupt_no_backup 路径属于阻塞启动的预期行为，请人工核对启动日志后重跑）'
      } else {
        Copy-Item $mainDb ($mainDb + '.pre-inject') -Force
        Write-Info ("注入：向主库写入垃圾字节（备份 {0} 份可用，最新 {1}）" -f $before['backups.files'], $before['backups.latest'])
        [IO.File]::WriteAllBytes($mainDb, ([byte[]](0x53, 0x51, 0x4C, 0x69, 0x74, 0x65, 0x20, 0x66, 0x6F, 0x72, 0x6D, 0x61, 0x74, 0x20, 0x43, 0x4F, 0x52, 0x52, 0x55, 0x50, 0x54)))
        Write-Info "启动应用，预期：坏库改名 .corrupt-{timestamp} 留证 → 从最近有效备份恢复 → health healthy"
        $healthy = Start-App $AppExe
        $after = Get-Digest $DataRoot
        New-Evidence 'corrupt-main' ("healthy={0}; corrupt_evidence={1}; main={2}→{3}" -f $healthy, $after['corrupt.evidence'], $before['xcagi.db.bytes'], $after['xcagi.db.bytes']) | Out-Null
        if ($healthy -and ([int64]$after['corrupt.evidence'] -gt 0)) {
          Write-Ok "主库损坏后自动恢复：坏库留证 + 备份还原 + health healthy"
          Record 'corrupt-main' 'PASS' ("health=healthy；.corrupt 留证 {0} 份；主库由备份恢复（{1} 字节）" -f $after['corrupt.evidence'], $after['xcagi.db.bytes'])
        } elseif ($healthy) {
          Write-Warn2 "启动健康但未见 .corrupt 留证：可能恢复逻辑未触发（请核对启动日志与 data 目录）"
          Record 'corrupt-main' 'PARTIAL' 'health=healthy 但缺少 .corrupt 留证，恢复路径未确认'
        } else {
          Record 'corrupt-main' 'FAIL' '主库损坏后启动失败且未自动恢复'
        }
        Stop-AppAll | Out-Null
        Remove-Item ($mainDb + '.pre-inject') -ErrorAction SilentlyContinue
      }
    }
  }
}

# ---------------------------------------------------------------- 人工场景指引
Write-Step "人工场景（脚本不自动执行）"
if ($CiMode) {
  Write-Info "CI 模式：disk-full / power-cut 为实体机人工场景，此处记 SKIP。"
  Record 'disk-full(人工)' 'SKIP' 'CI 环境：实体机场景待人工执行'
  Record 'power-cut(人工)' 'SKIP' 'CI 环境：实体机场景待人工执行'
} else {
Write-Host "▶ disk-full（磁盘写满）：" -ForegroundColor Cyan
Write-Host "  1) 用卷配额或小型 VHD 把数据根所在卷写到剩余 <100MB；"
Write-Host "  2) 正常使用中触发写入失败 → 观察应用报错是否友好、无静默数据损坏；"
Write-Host "  3) 释放空间后重启 → health healthy + 数据完好。"
Write-Host "▶ power-cut（异常断电）：" -ForegroundColor Cyan
Write-Host "  1) 业务写入过程中直接断电（PDU/拔电）；"
Write-Host "  2) 上电后启动 → health healthy + 最后一次已提交操作仍在（WAL+FULL 保证）；"
Write-Host "  3) 若主库损坏 → 应自动走 .corrupt 留证 + 备份恢复（同场景 4）。"
Write-Host "  ※ 两项请在实体测试机执行，并把观察结果补录进验收协议证据。"
$diskFull = Read-Host "  disk-full 执行结果 [PASS/FAIL/SKIP]"
$powerCut = Read-Host "  power-cut 执行结果 [PASS/FAIL/SKIP]"
Record 'disk-full(人工)' $(if ($diskFull) { $diskFull.ToUpper() } else { 'SKIP' }) '实体机场景'
Record 'power-cut(人工)' $(if ($powerCut) { $powerCut.ToUpper() } else { 'SKIP' }) '实体机场景'
}

# ---------------------------------------------------------------- 汇总
Write-Host ""
Write-Host ("=" * 72) -ForegroundColor DarkCyan
Write-Host (" 故障注入验收汇总（{0} · Windows x64）" -f $InstallRoot) -ForegroundColor White
Write-Host ("=" * 72) -ForegroundColor DarkCyan
$script:Results | Format-Table -AutoSize | Out-Host
$failCount = @($script:Results | Where-Object { $_.结果 -eq 'FAIL' }).Count
$partialCount = @($script:Results | Where-Object { $_.结果 -eq 'PARTIAL' }).Count
$skipCount = @($script:Results | Where-Object { $_.结果 -eq 'SKIP' }).Count
$passCount = @($script:Results).Count - $failCount - $partialCount - $skipCount
Write-Host ("统计：PASS={0} FAIL={1} PARTIAL={2} SKIP={3}" -f $passCount, $failCount, $partialCount, $skipCount) -ForegroundColor Gray

$receipt = [ordered]@{
  generated_at = (Get-Date).ToString('o')
  install_root = $InstallRoot
  data_root    = $DataRoot
  scenarios    = $script:Results
  summary      = @{ pass = $passCount; fail = $failCount; partial = $partialCount; skip = $skipCount }
}
$receiptPath = Join-Path $EvidenceDir 'fault-injection-receipt.json'
$receipt | ConvertTo-Json -Depth 4 | Set-Content -Path $receiptPath -Encoding UTF8
Write-Ok ("收据已写入：{0}" -f $receiptPath)

if ($failCount -gt 0) { exit 1 }
exit 0
