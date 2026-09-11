<#
.SYNOPSIS
XCAGI 桌面端 Windows（Win10/Win11）真实机验收引导脚本（协议 D1-3）。

.DESCRIPTION
面向在 Win10 / Win11 真实机上人工执行的逐步引导：
  1) 下载安装包（或使用本地包）并用 Get-FileHash 与 manifest.json 的 sha256 比对；
  2) 签名校验：按交付声明判定预期值（已签名构建要求 Valid；声明为 unsigned 的验收包
     只要求与声明的 NotSigned 一致并记 PARTIAL，不再对未签名包无差别判 FAIL）；
  3) 覆盖升级前基线采集（-OverwriteInstall，比对业务数据是否保留）；
  4) 安装：全新隔离安装到 C:\XCAGI-acceptance，或以 -OverwriteInstall 覆盖安装到已有安装目录；
  5) 安装版本核对 + 业务数据保留核对；
  6) 冷启动（计时 + 进程检测 + 健康检查 + 迁移/备份落到盘上）；
  7) 打印 OTA 与回滚两步的人工操作指引并记录执行结果；
每一步先输出「预期结果」，执行后要求人工确认 [Y/N]，最后汇总打印并提示填入证据模板。

用法（PowerShell 5.1+）：
  # 全新隔离安装（不影响任何已有安装）
  powershell -ExecutionPolicy Bypass -File acceptance-windows.ps1 -Version 1.0.0.1
  powershell -ExecutionPolicy Bypass -File acceptance-windows.ps1 -Version 1.0.0.1 -InstallerPath "C:\Users\me\Downloads\XCAGI-Enterprise-Setup-1.0.0.1-x64.exe"
  powershell -ExecutionPolicy Bypass -File acceptance-windows.ps1 -Version 1.0.0.1 -SkipLaunch

  # 覆盖升级验收（项2）：在已装旧版的机器上用正式安装包覆盖升级，校验业务数据保留
  powershell -ExecutionPolicy Bypass -File acceptance-windows.ps1 -Version 1.0.0.1 `
      -InstallerPath "C:\Users\me\Downloads\XCAGI-Enterprise-Setup-1.0.0.1-x64-unsigned.exe" `
      -ReceiptPath "C:\Users\me\Downloads\delivery-receipt.json" `
      -InstallRoot "$env:LOCALAPPDATA\Programs\XCAGI" -OverwriteInstall

安全边界：默认（不带 -OverwriteInstall）不触碰已有安装目录，装到 C:\XCAGI-acceptance；
带 -OverwriteInstall 时才覆盖写入已探测到的安装目录，且必须先采集业务数据基线。
OTA 与回滚只打印指引，不自动执行。
#>
[CmdletBinding()]
param(
  [string]$Version = "",
  [string]$InstallerPath = "",
  [switch]$SkipLaunch,
  # 覆盖升级验收：安装到已探测到的安装目录，并在升级前后比对业务数据保留。
  [switch]$OverwriteInstall,
  # 交付回执（delivery-receipt.json）：用于判定 signature_status，决定签名的预期值。
  [string]$ReceiptPath = "",
  # 显式指定预期签名状态：signed / unsigned / auto（默认 auto 时按回执或文件名推断）。
  [ValidateSet('auto', 'signed', 'unsigned')]
  [string]$ExpectedSignature = 'auto',
  # 业务数据根目录；默认 %APPDATA%\XCAGI（与 desktop/main.ts 的 userData 一致）。
  [string]$DataRoot = "",
  # 覆盖升级的目标安装目录；不指定时按 C:\XCAGI-acceptance → %LOCALAPPDATA%\Programs\XCAGI → %ProgramFiles%\XCAGI 顺序探测。
  [string]$InstallRoot = ""
)

$ErrorActionPreference = 'Stop'
try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch { }

$BaseUrl    = 'https://xiu-ci.com'
$AcceptRoot = 'C:\XCAGI-acceptance'
$HealthUrl  = 'http://127.0.0.1:17500/api/health'
$WorkDir    = Join-Path $env:TEMP ("xcagi-acceptance-" + (Get-Date -Format 'yyyyMMdd-HHmmss'))
$script:Results = New-Object System.Collections.Generic.List[object]

function Write-Step([string]$Name) {
  Write-Host ""
  Write-Host ("=" * 72) -ForegroundColor DarkCyan
  Write-Host ("STEP {0}" -f $Name) -ForegroundColor Cyan
  Write-Host ("=" * 72) -ForegroundColor DarkCyan
}
function Write-Ok([string]$Msg)  { Write-Host ("  [OK]   " + $Msg) -ForegroundColor Green }
function Write-Warn2([string]$Msg){ Write-Host ("  [WARN] " + $Msg) -ForegroundColor Yellow }
function Write-Fail([string]$Msg){ Write-Host ("  [FAIL] " + $Msg) -ForegroundColor Red }
function Write-Info([string]$Msg){ Write-Host ("  [INFO] " + $Msg) -ForegroundColor Gray }

# 输出预期结果 → 执行 → 人工确认 [Y/N]。返回 $true=确认通过。
function Confirm-Step([string]$Expected, [string]$Prompt) {
  Write-Host ("  预期结果：{0}" -f $Expected) -ForegroundColor Magenta
  $answer = Read-Host ("  人工确认 [Y/N] {0}" -f $Prompt)
  if ($answer -match '^[Yy]') { return $true } else { return $false }
}

function Record([string]$Step, [string]$Result, [string]$Detail) {
  $script:Results.Add([PSCustomObject]@{ 步骤 = $Step; 结果 = $Result; 说明 = $Detail })
  if ($Result -eq 'FAIL') { Write-Fail ("步骤 [{0}] 记录为 FAIL：{1}" -f $Step, $Detail) }
}

function Get-Manifest([string]$Ver) {
  $candidates = @(
    ("{0}/xcagi-v{1}/manifest.json" -f $BaseUrl, $Ver),
    ("{0}/releases/stable/manifest.json" -f $BaseUrl)
  )
  foreach ($url in $candidates) {
    try {
      $tmp = Join-Path $WorkDir 'manifest.json'
      Invoke-WebRequest -Uri $url -OutFile $tmp -UseBasicParsing -TimeoutSec 30
      Write-Ok ("manifest 获取成功：{0}" -f $url)
      return Get-Content $tmp -Raw -Encoding UTF8 | ConvertFrom-Json
    } catch { Write-Info ("manifest 候选不可达：{0}" -f $url) }
  }
  return $null
}

# 在 manifest 的 enterprise.win 条目里取 url/sha256/filename；返回 hashtable。
function Get-WinEntry($Manifest) {
  if ($null -eq $Manifest) { return $null }
  foreach ($channelName in @('official_download', 'auto_update')) {
    $ent = $null
    try { $ent = $Manifest.channels.$channelName.enterprise } catch { $ent = $null }
    if ($null -ne $ent -and $ent.win) {
      return @{ url = $ent.win.url; sha256 = $ent.win.sha256; filename = $ent.win.filename; size = $ent.win.size }
    }
  }
  return $null
}

# 在候选目录里找包含 resources\build-info.json 的安装根目录。
function Find-InstallRoot {
  $candidates = @(
    $AcceptRoot,
    (Join-Path $env:LOCALAPPDATA 'Programs\XCAGI'),
    (Join-Path ${env:ProgramFiles} 'XCAGI')
  )
  foreach ($root in $candidates) {
    if (Test-Path (Join-Path $root 'resources\build-info.json')) { return $root }
  }
  return $null
}

# 解析本次交付声明的签名状态（signed / unsigned / unknown）。
# 优先 -ExpectedSignature；其次交付回执 signature_status；再次文件名特征（unsigned / macalign）。
function Get-DeclaredSignatureStatus {
  param([string]$ExePath, [string]$Receipt)
  if ($script:ExpectedSignature -ne 'auto') { return $script:ExpectedSignature }
  if ($Receipt -and (Test-Path $Receipt)) {
    try {
      $r = Get-Content $Receipt -Raw -Encoding UTF8 | ConvertFrom-Json
      if ($r.signature_status) { return ([string]$r.signature_status).ToLower() }
      if ($r.authenticode_status) {
        $a = ([string]$r.authenticode_status).ToLower()
        if ($a -eq 'notsigned' -or $a -eq 'unsigned') { return 'unsigned' }
        return 'signed'
      }
    } catch { Write-Info ("交付回执解析失败：{0}" -f $_) }
  }
  $declaredUnsigned = $false
  foreach ($url in @(
    ("{0}/download-windows-hotfix.json" -f $BaseUrl),
    ("{0}/releases/stable/enterprise/download-windows-hotfix.json" -f $BaseUrl)
  )) {
    try {
      $h = Invoke-RestMethod -Uri $url -UseBasicParsing -TimeoutSec 20
      if ($h.signature_status) { return ([string]$h.signature_status).ToLower() }
    } catch { }
  }
  if ($ExePath -and ((Split-Path $ExePath -Leaf) -match 'unsigned|macalign')) { $declaredUnsigned = $true }
  if ($declaredUnsigned) { return 'unsigned' }
  return 'unknown'
}

# 业务数据快照：主库/向量库大小与时间、Mod 库与业务子目录文件数、自动备份数量与最新备份。
function Get-BusinessDataDigest([string]$Root) {
  $d = [ordered]@{}
  $mainDb = Join-Path $Root 'data\xcagi.db'
  if (Test-Path $mainDb) {
    $i = Get-Item $mainDb
    $d['xcagi.db.bytes'] = $i.Length
    $d['xcagi.db.mtime'] = $i.LastWriteTimeUtc.ToString('o')
  } else { $d['xcagi.db.bytes'] = -1; $d['xcagi.db.mtime'] = '' }
  $vecDb = Join-Path $Root 'data\excel_vectors.db'
  $d['excel_vectors.db.bytes'] = if (Test-Path $vecDb) { (Get-Item $vecDb).Length } else { -1 }
  $modDbDir = Join-Path $Root 'data\mod_dbs'
  $d['mod_dbs.files'] = if (Test-Path $modDbDir) { @(Get-ChildItem $modDbDir -File -Recurse -ErrorAction SilentlyContinue).Count } else { 0 }
  foreach ($sub in @('uploads', 'mods', 'models')) {
    $p = Join-Path $Root $sub
    $d["$sub.files"] = if (Test-Path $p) { @(Get-ChildItem $p -File -Recurse -ErrorAction SilentlyContinue).Count } else { 0 }
  }
  $bks = @(Get-ChildItem (Join-Path $Root 'backups') -File -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -match '^xcagi-.+?(-\w+)?-\d{14}\.db$' })
  $d['backups.files'] = $bks.Count
  $d['backups.latest'] = if ($bks.Count) { ($bks | Sort-Object LastWriteTime -Descending | Select-Object -First 1).Name } else { '' }
  return $d
}

function Format-Digest([object]$Digest) {
  return (($Digest.Keys | ForEach-Object { "{0}={1}" -f $_, $Digest[$_] }) -join ' ')
}

# 对比升级前后快照：返回 @{ lost = @(...); gained = @(...) }。零值/缺失不作为「丢失」证据。
function Compare-DataDigest($Before, $After) {
  $lost = New-Object System.Collections.Generic.List[string]
  $gained = New-Object System.Collections.Generic.List[string]
  foreach ($k in @('xcagi.db.bytes', 'excel_vectors.db.bytes', 'mod_dbs.files', 'uploads.files', 'mods.files', 'models.files')) {
    $b = [int64]$Before[$k]; $a = [int64]$After[$k]
    if ($b -gt 0 -and $a -lt $b) { $lost.Add(("{0}: {1} → {2}" -f $k, $b, $a)) }
    elseif ($a -gt $b) { $gained.Add(("{0}: {1} → {2}" -f $k, $b, $a)) }
  }
  return @{ lost = $lost; gained = $gained }
}

Write-Host ""
Write-Host "XCAGI 桌面端 Windows 真实机验收引导（协议：docs/e2e/desktop-real-machine-acceptance-protocol.md）" -ForegroundColor White
Write-Host ("工作目录：{0}" -f $WorkDir)
New-Item -ItemType Directory -Force -Path $WorkDir | Out-Null
if (-not $DataRoot) { $DataRoot = Join-Path $env:APPDATA 'XCAGI' }
if ($OverwriteInstall) { Write-Host ("模式：覆盖升级验收（目标安装目录将被覆盖，业务数据根 {0}）" -f $DataRoot) -ForegroundColor Yellow }
else { Write-Host "模式：全新隔离安装（不触碰已有安装）" -ForegroundColor Gray }

# ---------------------------------------------------------------- STEP 1 版本与 manifest
Write-Step "1/8 版本确认与 manifest 获取"
if (-not $Version) {
  $Version = Read-Host "  未提供 -Version。请输入要验收的四段产品版本（如 1.0.0.1，见 FHD/VERSION.md）"
  if ($Version -notmatch '^\d+\.\d+\.\d+\.\d+$') { throw ("版本号必须是四段产品版本，当前为：{0}" -f $Version) }
}
Write-Ok ("验收版本：{0}" -f $Version)

$manifest = Get-Manifest $Version
$winEntry = Get-WinEntry $manifest
if ($null -eq $winEntry) {
  $winFilename = "XCAGI-Enterprise-Setup-{0}-x64.exe" -f $Version
  $winUrl      = "{0}/xcagi-v{1}/enterprise/{2}" -f $BaseUrl, $Version, $winFilename
  Write-Warn2 ("manifest 不可达或无 win 条目，按命名约定使用：{0}" -f $winUrl)
  Write-Warn2 "SHA256 将无线上基准（记录实测值并在证据中注明）。"
  $expectedSha = ""
} else {
  $winUrl      = $winEntry.url
  $winFilename = $winEntry.filename
  $expectedSha = $winEntry.sha256
  Write-Ok ("manifest win 条目：{0}" -f $winFilename)
  if ($manifest.git_sha) { Write-Ok ("manifest git_sha：{0}" -f $manifest.git_sha) }
}

# ---------------------------------------------------------------- STEP 2 下载与 SHA256
Write-Step "2/8 下载安装包 + SHA256 校验"
if ($InstallerPath) {
  if (-not (Test-Path $InstallerPath)) { throw ("指定的 -InstallerPath 不存在：{0}" -f $InstallerPath) }
  $exePath = $InstallerPath
  Write-Ok ("跳过下载，使用本地安装包：{0}" -f $exePath)
} else {
  $exePath = Join-Path $WorkDir $winFilename
  Write-Host ("  开始下载：{0}" -f $winUrl)
  Write-Host ("  → {0}（约 200MB，请耐心等待）" -f $exePath)
  Invoke-WebRequest -Uri $winUrl -OutFile $exePath -UseBasicParsing -TimeoutSec 1800
  Write-Ok "下载完成"
}

$receipt = $null
if ($ReceiptPath -and (Test-Path $ReceiptPath)) {
  try {
    $receipt = Get-Content $ReceiptPath -Raw -Encoding UTF8 | ConvertFrom-Json
    Write-Ok ("交付回执：{0}（sha256={1} signature_status={2}）" -f (Split-Path $ReceiptPath -Leaf), $receipt.sha256, $receipt.signature_status)
  } catch { Write-Warn2 ("交付回执解析失败：{0}" -f $_) }
}
if (-not $expectedSha -and $receipt -and $receipt.sha256) {
  $expectedSha = [string]$receipt.sha256
  Write-Ok ("SHA256 以交付回执为准：{0}" -f $expectedSha)
}

$actualSha = (Get-FileHash -Path $exePath -Algorithm SHA256).Hash.ToLower()
Write-Ok ("实测 SHA256：{0}" -f $actualSha)
if ($expectedSha) {
  if ($actualSha -eq $expectedSha.ToLower()) {
    Write-Ok ("与 manifest 一致：{0}" -f $expectedSha)
    Record '2.下载与SHA256' 'PASS' ("SHA256 与 manifest 一致：{0}" -f $actualSha)
  } else {
    Write-Fail ("SHA256 不一致！manifest 期望：{0}" -f $expectedSha)
    Record '2.下载与SHA256' 'FAIL' ("实测 {0} vs manifest {1}（疑似篡改/损坏，P0 阻断）" -f $actualSha, $expectedSha)
  }
} else {
  Write-Warn2 "manifest 无该版本条目，SHA256 无线上基准——实测值已输出，请记入证据。"
  Record '2.下载与SHA256' 'PARTIAL' ("manifest 无基准，实测 SHA256={0}" -f $actualSha)
}

# ---------------------------------------------------------------- STEP 3 签名校验
Write-Step "3/8 Authenticode 签名校验（按交付声明判定预期值）"
Write-Host "  执行命令：Get-AuthenticodeSignature"
$signature = Get-AuthenticodeSignature -FilePath $exePath
$declaredSig = Get-DeclaredSignatureStatus -ExePath $exePath -Receipt $ReceiptPath
Write-Host ("  Status        : {0}" -f $signature.Status)
if ($signature.SignerCertificate) {
  Write-Host ("  Subject       : {0}" -f $signature.SignerCertificate.Subject)
  Write-Host ("  NotAfter      : {0}" -f $signature.SignerCertificate.NotAfter)
  Write-Host ("  TimeStamper   : {0}" -f $signature.TimeStamperCertificate.Subject)
} else {
  Write-Host "  SignerCertificate: （无——包未签名）" 
}
Write-Host ("  交付声明签名状态：{0}（signed=必须 Valid；unsigned=验收包，签名项记 PARTIAL 不阻断）" -f $declaredSig) -ForegroundColor Magenta

if ($declaredSig -eq 'signed') {
  Write-Host "  预期结果：Status=Valid，Subject 为发布方证书，且存在可信时间戳" -ForegroundColor Magenta
  if ($signature.Status -eq 'Valid') {
    Write-Ok "签名有效"
    Record '3.签名校验' 'PASS' ("Status=Valid Subject={0}" -f $signature.SignerCertificate.Subject)
  } else {
    Write-Fail ("声明为已签名交付，但实际签名状态为 {0}（必须阻断签字）" -f $signature.Status)
    Record '3.签名校验' 'FAIL' ("声明 signed 但 Status={0}" -f $signature.Status)
  }
} elseif ($declaredSig -eq 'unsigned') {
  Write-Host "  预期结果：Status=NotSigned（本包为未签名验收包，仅用于上机覆盖升级/功能验收）" -ForegroundColor Magenta
  Write-Warn2 "未签名包不得进入稳定自动更新通道，不得作为公开下载交付物。"
  if ($signature.Status -eq 'NotSigned') {
    Write-Ok "签名状态与声明一致：NotSigned（已知风险，非阻断）"
    Record '3.签名校验' 'PARTIAL' ("按声明 unsigned 验收：Status=NotSigned；包哈希已在 STEP 2 与回执核对")
  } else {
    Write-Ok ("实际签名状态 {0} 优于声明，请更新交付声明与回执" -f $signature.Status)
    Record '3.签名校验' 'PASS' ("声明 unsigned 但实际 Status={0}，需回写声明" -f $signature.Status)
  }
} else {
  Write-Host "  预期结果：Status=Valid，Subject 为发布方证书，且存在可信时间戳" -ForegroundColor Magenta
  Write-Warn2 "未能判定交付声明的签名状态（无回执/无 -ExpectedSignature）。按已签名交付从严判定。"
  if ($signature.Status -eq 'Valid') {
    Write-Ok "签名有效"
    Record '3.签名校验' 'PASS' ("Status=Valid Subject={0}" -f $signature.SignerCertificate.Subject)
  } else {
    Write-Fail ("签名状态异常：{0}（历史审计曾发现公网 EXE 无 Authenticode 签名结构，必须阻断签字）" -f $signature.Status)
    Record '3.签名校验' 'FAIL' ("Status={0}，且交付未声明为 unsigned" -f $signature.Status)
  }
}
if (Confirm-Step "签名信息与上述预期一致" "签名校验结果无误？") { } else {
  Record '3.签名校验' 'FAIL' '人工确认不通过'
}

# ---------------------------------------------------------------- STEP 4 覆盖升级基线
Write-Step "4/8 升级前基线采集（仅 -OverwriteInstall）"
$baselineRoot = $null
$baselineDigest = $null
$markerFile = Join-Path $DataRoot (".xcagi-acceptance-marker-{0}.txt" -f (Get-Date -Format 'yyyyMMdd-HHmmss'))
if (-not $OverwriteInstall) {
  Write-Info "未指定 -OverwriteInstall：跳过基线采集（全新隔离安装无既有业务数据）。"
  Record '4.升级基线' 'SKIP' '全新隔离安装模式'
} else {
  if ($InstallRoot) {
    if (Test-Path (Join-Path $InstallRoot 'resources\build-info.json')) { $baselineRoot = $InstallRoot }
    else { Write-Fail ("-InstallRoot 指定的目录不含 resources\build-info.json：{0}" -f $InstallRoot) }
  } else { $baselineRoot = Find-InstallRoot }
  if (-not $baselineRoot) {
    Write-Fail "未能定位已有安装目录（可用 -InstallRoot 显式指定；默认候选：C:\XCAGI-acceptance、%LOCALAPPDATA%\Programs\XCAGI、%ProgramFiles%\XCAGI）——覆盖升级验收缺少升级前基线。"
    Record '4.升级基线' 'FAIL' '未找到已有安装，无法做覆盖升级验收'
  } else {
    $beforeBuild = Join-Path $baselineRoot 'resources\build-info.json'
    $beforeInfo = Get-Content $beforeBuild -Raw -Encoding UTF8 | ConvertFrom-Json
    Write-Ok ("升级前安装目录：{0}" -f $baselineRoot)
    Write-Ok ("升级前 build-info：version={0} gitSha={1}" -f $beforeInfo.version, $beforeInfo.gitSha)
    if ($beforeInfo.version -eq $Version) {
      Write-Warn2 ("升级前版本已等于验收目标 {0}，本次不构成覆盖升级（请从更低版本机器上执行）。" -f $Version)
    }
    $baselineDigest = Get-BusinessDataDigest $DataRoot
    Write-Ok ("升级前业务数据：{0}" -f (Format-Digest $baselineDigest))
    if (-not (Test-Path $DataRoot)) { New-Item -ItemType Directory -Force -Path $DataRoot | Out-Null }
    Set-Content -Path $markerFile -Value ("xcagi-acceptance-overwrite baseline version={0} gitSha={1}" -f $beforeInfo.version, $beforeInfo.gitSha) -Encoding UTF8
    Write-Ok ("已写入数据保留标记：{0}" -f $markerFile)
    Record '4.升级基线' 'PASS' ("from version={0} gitSha={1}" -f $beforeInfo.version, $beforeInfo.gitSha)
  }
}

# ---------------------------------------------------------------- STEP 5 安装 / 覆盖升级
Write-Step "5/8 安装 / 覆盖升级"
$targetRoot = $AcceptRoot
if ($OverwriteInstall) {
  if ($baselineRoot) { $targetRoot = $baselineRoot }
  else { Write-Warn2 ("覆盖升级模式未定位到已有安装，回退为隔离安装到 {0}" -f $AcceptRoot) }
  if ($targetRoot -match '\s') {
    Write-Warn2 ("目标目录含空格（{0}）：NSIS 的 /D= 不接受带空格路径，请改用双击安装（方式 A）并手动选择该目录。" -f $targetRoot)
  }
}
Write-Host ("  安装目标：{0}（{1}）" -f $targetRoot, $(if ($OverwriteInstall) { '覆盖升级' } else { '全新隔离' }))
Write-Host "  方式 A：双击安装包，按提示完成；"
Write-Host "  方式 B：脚本静默安装（命令如下）："
Write-Host ("      Start-Process -FilePath '{0}' -ArgumentList '/S','/D={1}' -Wait" -f $exePath, $targetRoot) -ForegroundColor White
Write-Host "      （/S 静默；/D= 自定义目录必须放最后、路径不含中文与空格）"
$running = Get-CimInstance Win32_Process -Filter "Name='XCAGI.exe'" -ErrorAction SilentlyContinue
if ($running) {
  Write-Fail "检测到正在运行的 XCAGI 实例（安装器可能因文件占用失败）。请先完全退出（托盘右键 → 退出）后重跑。"
  Record '5.安装' 'FAIL' '安装前存在运行中的 XCAGI 实例'
}
$installChoice = Read-Host "  请选择执行方式 [A=我自己双击 / B=脚本帮我静默安装]"
if ($installChoice -match '^[Bb]') {
  Write-Info ("静默安装到 {0} ..." -f $targetRoot)
  $proc = Start-Process -FilePath $exePath -ArgumentList '/S', ("/D={0}" -f $targetRoot) -PassThru -Wait
  Write-Ok ("安装进程退出码：{0}" -f $proc.ExitCode)
} else {
  Write-Info "请现在双击安装包完成安装，完成后回到此窗口继续。"
}
$expectIcon = if ($OverwriteInstall) { "安装完成无报错；既有安装目录被覆盖为 {0} 版本" -f $Version } else { "开始菜单/桌面出现 XCAGI 图标，无安装报错弹窗" }
if (Confirm-Step $expectIcon "安装是否完成且无报错？") {
  Record '5.安装' 'PASS' ("{0}·方式 {1}" -f $(if ($OverwriteInstall) { '覆盖升级' } else { '全新安装' }), $(if ($installChoice -match '^[Bb]') { '静默 /S' } else { '双击' }))
} else {
  Record '5.安装' 'FAIL' '人工报告安装失败或出现报错弹窗'
}

# ---------------------------------------------------------------- STEP 6 版本核对 + 数据保留
Write-Step "6/8 安装版本核对 + 业务数据保留核对"
$installRoot = if ($InstallRoot -and (Test-Path (Join-Path $InstallRoot 'resources\build-info.json'))) { $InstallRoot } else { Find-InstallRoot }
if ($installRoot) {
  $buildInfoPath = Join-Path $installRoot 'resources\build-info.json'
  $buildInfo = Get-Content $buildInfoPath -Raw -Encoding UTF8 | ConvertFrom-Json
  Write-Ok ("安装根目录   : {0}" -f $installRoot)
  Write-Ok ("build-info   : version={0} gitSha={1} builtAt={2}" -f $buildInfo.version, $buildInfo.gitSha, $buildInfo.builtAt)
  $exePathInstalled = Join-Path $installRoot 'XCAGI.exe'
  if (Test-Path $exePathInstalled) {
    Write-Ok ("ProductVersion: {0}" -f (Get-Item $exePathInstalled).VersionInfo.ProductVersion)
  }
  $skuPath = Join-Path $installRoot 'resources\product-sku.json'
  if (Test-Path $skuPath) { Write-Ok ("product-sku  : {0}" -f (Get-Content $skuPath -Raw -Encoding UTF8).Trim()) }
  Write-Host ("  预期结果：version 为四段 {0}，gitSha 与 manifest 一致，sku=enterprise" -f $Version) -ForegroundColor Magenta
  if ($buildInfo.version -eq $Version) {
    Record '6.版本核对' 'PASS' ("version={0} gitSha={1}" -f $buildInfo.version, $buildInfo.gitSha)
  } else {
    Record '6.版本核对' 'FAIL' ("build-info version={0} 与验收目标 {1} 不一致" -f $buildInfo.version, $Version)
  }
  if ($OverwriteInstall) {
    if ($baselineRoot -and ($installRoot -ne $baselineRoot)) {
      Write-Warn2 ("覆盖后定位到的安装目录 {0} 与升级前 {1} 不同，请确认未被安装到新目录。" -f $installRoot, $baselineRoot)
    }
    if ($receipt -and $receipt.git_sha -and $buildInfo.gitSha -and ($buildInfo.gitSha -ne $receipt.git_sha)) {
      Write-Warn2 ("build-info gitSha={0} 与交付回执 git_sha={1} 不一致，请在证据中注明。" -f $buildInfo.gitSha, $receipt.git_sha)
    }
  }
} else {
  Write-Fail "未找到包含 resources\build-info.json 的安装目录（候选：C:\XCAGI-acceptance、%LOCALAPPDATA%\Programs\XCAGI、%ProgramFiles%\XCAGI）"
  Record '6.版本核对' 'FAIL' '未定位到安装目录/build-info.json'
}
if ($installRoot -and (Confirm-Step "version 四段一致、sku 正确" "版本核对无误？")) { } elseif ($installRoot) {
  Record '6.版本核对' 'FAIL' '人工确认不通过'
}

if (-not $OverwriteInstall) {
  Write-Info "全新隔离安装模式：无升级前业务数据，跳过数据保留核对。"
  Record '6b.数据保留' 'SKIP' '全新隔离安装模式'
} else {
  $afterDigest = Get-BusinessDataDigest $DataRoot
  Write-Ok ("升级后业务数据：{0}" -f (Format-Digest $afterDigest))
  $markerKept = Test-Path $markerFile
  if ($markerKept) { Write-Ok ("数据保留标记仍在：{0}" -f (Split-Path $markerFile -Leaf)) }
  else { Write-Fail ("数据保留标记丢失：{0}" -f $markerFile) }
  $diff = Compare-DataDigest $baselineDigest $afterDigest
  if ($diff.lost.Count -gt 0) {
    foreach ($l in $diff.lost) { Write-Fail ("业务数据减少：{0}" -f $l) }
    Record '6b.数据保留' 'FAIL' ("覆盖升级后业务数据减少：" + ($diff.lost -join '; '))
  } elseif (-not $markerKept) {
    Record '6b.数据保留' 'FAIL' '用户数据目录被清空（数据保留标记丢失）'
  } else {
    Write-Ok "业务数据未丢失（文件数/库大小均未减少）"
    $gainNote = if ($diff.gained.Count -gt 0) { "；新增：" + ($diff.gained -join '; ') } else { '' }
    Record '6b.数据保留' 'PASS' ("覆盖升级后 userData 保留，库/子目录未减少{0}" -f $gainNote)
  }
  if (Confirm-Step "覆盖升级后旧数据（库、上传、Mod）仍可访问，无重建/清空迹象" "业务数据保留确认？") { } else {
    Record '6b.数据保留' 'FAIL' '人工报告升级后业务数据丢失'
  }
}

# ---------------------------------------------------------------- STEP 7 冷启动
Write-Step "7/8 冷启动（计时 + 进程检测 + 健康检查 + 迁移/备份落盘）"
if ($SkipLaunch) {
  Write-Warn2 "已指定 -SkipLaunch：跳过真实启动。请在证据中注明「启动步骤以代码评审 + CI 冒烟替代」。"
  Record '7.冷启动' 'SKIP' '执行人指定跳过真实启动'
} else {
  $existing = Get-CimInstance Win32_Process -Filter "Name='XCAGI.exe'" -ErrorAction SilentlyContinue
  if ($existing) {
    foreach ($p in $existing) { Write-Host ("    已有实例: PID={0} Path={1}" -f $p.ProcessId, $p.ExecutablePath) }
    Write-Fail "检测到正在运行的 XCAGI 实例（单实例锁与 17500 端口会冲突）。请先完全退出（托盘右键 → 退出）后重跑，或改用 -SkipLaunch。"
    Record '7.冷启动' 'FAIL' '存在已运行实例，冷启动前置条件不满足'
  } else {
    $targetExe = if ($installRoot) { Join-Path $installRoot 'XCAGI.exe' } else { $null }
    if (-not ($targetExe -and (Test-Path $targetExe))) {
      Write-Fail ("找不到可启动的 XCAGI.exe：{0}" -f $targetExe)
      Record '7.冷启动' 'FAIL' 'XCAGI.exe 不存在'
    } else {
      Write-Host "  预期结果：主窗口在 60 秒内完整出现（无白屏）；/api/health 返回 status=healthy" -ForegroundColor Magenta
      Write-Info "正在启动并计时 ..."
      $elapsed = Measure-Command { Start-Process -FilePath $targetExe | Out-Null }
      Write-Ok ("Start-Process 耗时：{0:N1} 秒（此后等待窗口出现，掐表到主界面完整显示）" -f $elapsed.TotalSeconds)

      $newProc = $null
      for ($i = 0; $i -lt 120; $i++) {
        Start-Sleep -Milliseconds 500
        $newProc = Get-CimInstance Win32_Process -Filter "Name='XCAGI.exe'" -ErrorAction SilentlyContinue |
          Where-Object { $_.ExecutablePath -eq $targetExe } | Select-Object -First 1
        if ($newProc) { break }
      }
      if ($newProc) {
        Write-Ok ("验收实例进程已出现：PID={0}" -f $newProc.ProcessId)
      } else {
        Write-Fail "60 秒内未检测到验收实例进程"
        Record '7.冷启动' 'FAIL' '进程未出现'
      }

      Start-Sleep -Seconds 8
      $healthOk = $false
      for ($i = 0; $i -lt 60; $i++) {
        try { $health = Invoke-RestMethod -Uri $HealthUrl -TimeoutSec 3; $healthOk = $true; break }
        catch { Start-Sleep -Seconds 1 }
      }
      if ($healthOk) {
        Write-Ok ("健康检查通过：{0}" -f ($health | ConvertTo-Json -Compress -Depth 3))
        Record '7.冷启动' 'PASS' ("PID={0} health=healthy" -f $newProc.ProcessId)
      } else {
        Write-Fail ("健康检查 60 秒内未通过（{0}）" -f $HealthUrl)
        Record '7.冷启动' 'FAIL' 'health 未通过'
      }
      Write-Info "请现在对主窗口截图（PrtSc 或 Win+Shift+S），保存到证据目录 assets/ 后按 Y 继续。"
      if (Confirm-Step "截图已保存且主界面渲染完整（无白屏）" "主窗口截图与渲染确认？") { } else {
        Record '7.冷启动' 'FAIL' '人工报告白屏或渲染异常'
      }

      if ($OverwriteInstall) {
        Write-Host ""
        Write-Info "覆盖升级终检：启动迁移后应产生新备份，且迁移到 head（alembic_version）。"
        $finalDigest = Get-BusinessDataDigest $DataRoot
        if ([int64]$finalDigest['backups.files'] -gt [int64]$baselineDigest['backups.files']) {
          Write-Ok ("启动迁移已产生新备份：{0}（{1} → {2}）" -f $finalDigest['backups.latest'], $baselineDigest['backups.files'], $finalDigest['backups.files'])
          Record '7b.迁移备份' 'PASS' ("新增备份 {0}" -f $finalDigest['backups.latest'])
        } elseif ([string]$finalDigest['backups.latest'] -eq [string]$baselineDigest['backups.latest']) {
          Write-Warn2 ("备份数量未增加（最新仍为 {0}）：若迁移无版本变化则属预期，请核对日志确认。" -f $finalDigest['backups.latest'])
          Record '7b.迁移备份' 'PARTIAL' ("备份未新增，最新={0}（需核对是否发生迁移）" -f $finalDigest['backups.latest'])
        } else {
          Record '7b.迁移备份' 'PASS' ("备份最新={0}" -f $finalDigest['backups.latest'])
        }
        $finalDiff = Compare-DataDigest $baselineDigest $finalDigest
        if ($finalDiff.lost.Count -gt 0) {
          foreach ($l in $finalDiff.lost) { Write-Fail ("启动迁移后业务数据减少：{0}" -f $l) }
          Record '7c.迁移后数据' 'FAIL' ("启动迁移后业务数据减少：" + ($finalDiff.lost -join '; '))
        } else {
          Record '7c.迁移后数据' 'PASS' '启动迁移后业务数据未减少'
        }
      }
    }
  }
}

# ---------------------------------------------------------------- STEP 8 OTA + 回滚（人工）
Write-Step "8/8 OTA 与回滚（人工执行，脚本只给指引）"
Write-Host ""
Write-Host "▶ OTA（协议第 4 节）：" -ForegroundColor Cyan
Write-Host ("  1) 查看更新源：Invoke-RestMethod {0}/releases/stable/enterprise/latest.yml" -f $BaseUrl)
Write-Host "  2) 打开 XCAGI → 设置 → 检查更新 → 下载完成后点「立即重启安装」；"
Write-Host "  3) 观察期（约 5 秒稳定性窗口）内不要强制退出；"
Write-Host "  4) 复核：Get-Content \"<安装目录>\resources\build-info.json\"；Invoke-RestMethod http://127.0.0.1:17500/api/health；"
Write-Host "     Get-Content \"$env:APPDATA\XCAGI\rollback-marker.json\"（应提示不存在 = 已提交）。"
Write-Host "  ※ 无新版本可升时记 SKIP（无升级目标），引用 desktop-ota-closed-loop-20260724 证据。"
$otaResult = Read-Host "  OTA 执行结果 [PASS/FAIL/SKIP]"
$otaNote   = Read-Host "  OTA 备注（升级前后版本号/更新源 URL/现象，一行）"
Record '8a.OTA' $(if ($otaResult) { $otaResult.ToUpper() } else { 'SKIP' }) $otaNote

Write-Host ""
Write-Host "▶ 回滚（协议第 5 节）：" -ForegroundColor Cyan
Write-Host "  路径 A（观察期自动回滚，需专用验收机构造坏更新）：更新后启动失败 → 自动还原旧版本；"
Write-Host ("     取证：Get-Content \"$env:APPDATA\XCAGI\rollback-applied.json\"（应含 reason/fromVersion/toVersion）")
Write-Host "  路径 B（降级安装）：从历史版本目录下载旧版 exe 覆盖安装，确认版本回到旧版且 health healthy。"
Write-Host "  ※ 未注入坏更新时记 PARTIAL，引用 rollback.test.ts + update-rollback.e2e.spec.ts 佐证。"
$rbResult = Read-Host "  回滚执行结果 [PASS/FAIL/PARTIAL/SKIP]"
$rbNote   = Read-Host "  回滚备注（方式/回滚后版本号/健康状态，一行）"
Record '8b.回滚' $(if ($rbResult) { $rbResult.ToUpper() } else { 'SKIP' }) $rbNote

# ---------------------------------------------------------------- 汇总
Write-Host ""
Write-Host ("=" * 72) -ForegroundColor DarkCyan
Write-Host (" 验收结果汇总（版本 {0} · Windows x64 · {1}）" -f $Version, $(if ($OverwriteInstall) { '覆盖升级' } else { '全新隔离安装' })) -ForegroundColor White
Write-Host ("=" * 72) -ForegroundColor DarkCyan
$script:Results | Format-Table -AutoSize | Out-Host
$failCount = @($script:Results | Where-Object { $_.结果 -eq 'FAIL' }).Count
$partialCount = @($script:Results | Where-Object { $_.结果 -eq 'PARTIAL' }).Count
$skipCount = @($script:Results | Where-Object { $_.结果 -eq 'SKIP' }).Count
Write-Host ("统计：PASS={0} FAIL={1} PARTIAL={2} SKIP={3}" -f (@($script:Results).Count - $failCount - $partialCount - $skipCount), $failCount, $partialCount, $skipCount) -ForegroundColor Gray
if ($partialCount -gt 0) {
  Write-Host "PARTIAL 项（未签名包签名校验、备份未新增等）不阻断本轮上机验收，但必须在证据文件中逐条记录原因。" -ForegroundColor Yellow
}
Write-Host "【证据归档】按模板逐项填写：" -ForegroundColor Yellow
Write-Host "  模板   ：FHD/docs/e2e/templates/desktop-acceptance-template.md"
Write-Host ("  另存为 ：FHD/docs/evidence/e2e/desktop-real-machine-acceptance-{0}-win10.md（或 win11）" -f $Version)
Write-Host "  截图   ：FHD/docs/evidence/e2e/assets/"
Write-Host ("  证据要点：模式={0}；安装目录={1}；业务数据根={2}" -f $(if ($OverwriteInstall) { '覆盖升级' } else { '全新隔离' }), $installRoot, $DataRoot)
if ($OverwriteInstall) {
  Write-Host "           覆盖升级：升级前/后版本号、备份文件名、库与子目录文件数前后值（见上文 STEP 4/6/7 输出）"
  Write-Host ("           数据保留标记（归档后请删除）：{0}" -f $markerFile)
}
Write-Host ("  工作目录（含下载的安装包与 manifest）：{0}" -f $WorkDir)
Write-Host ("=" * 72) -ForegroundColor DarkCyan

if ($failCount -gt 0) { Write-Host ("结论：存在 {0} 项 FAIL —— 该平台验收未闭环。" -f $failCount) -ForegroundColor Red; exit 1 }
Write-Host "结论：本轮引导完成，无 FAIL 记录（以人工确认与证据文件为准）。" -ForegroundColor Green
exit 0
