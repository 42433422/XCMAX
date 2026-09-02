<#
.SYNOPSIS
XCAGI 桌面端 Windows（Win10/Win11）真实机验收引导脚本（协议 D1-3）。

.DESCRIPTION
面向在 Win10 / Win11 真实机上人工执行的逐步引导：
  1) 下载安装包（或使用本地包）并用 Get-FileHash 与 manifest.json 的 sha256 比对；
  2) Get-AuthenticodeSignature 签名校验；
  3) 安装（双击提示或 /S 静默安装到独立目录，不影响现有安装）；
  4) 冷启动计时（Measure-Command + 进程检测）+ 版本读取 + 后端健康检查；
  5) 打印 OTA 与回滚两步的人工操作指引并记录执行结果；
每一步先输出「预期结果」，执行后要求人工确认 [Y/N]，最后汇总打印并提示填入证据模板。

用法（PowerShell 5.1+）：
  powershell -ExecutionPolicy Bypass -File acceptance-windows.ps1 -Version 1.0.0.1
  powershell -ExecutionPolicy Bypass -File acceptance-windows.ps1 -Version 1.0.0.1 -InstallerPath "C:\Users\me\Downloads\XCAGI-Enterprise-Setup-1.0.0.1-x64.exe"
  powershell -ExecutionPolicy Bypass -File acceptance-windows.ps1 -Version 1.0.0.1 -SkipLaunch

安全边界：不触碰已有安装目录（默认建议安装到 C:\XCAGI-acceptance）；OTA 与回滚只打印指引，不自动执行。
#>
[CmdletBinding()]
param(
  [string]$Version = "",
  [string]$InstallerPath = "",
  [switch]$SkipLaunch
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

Write-Host ""
Write-Host "XCAGI 桌面端 Windows 真实机验收引导（协议：docs/e2e/desktop-real-machine-acceptance-protocol.md）" -ForegroundColor White
Write-Host ("工作目录：{0}" -f $WorkDir)
New-Item -ItemType Directory -Force -Path $WorkDir | Out-Null

# ---------------------------------------------------------------- STEP 1 版本与 manifest
Write-Step "1/7 版本确认与 manifest 获取"
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
Write-Step "2/7 下载安装包 + SHA256 校验"
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
Write-Step "3/7 Authenticode 签名校验"
Write-Host "  执行命令：Get-AuthenticodeSignature"
$signature = Get-AuthenticodeSignature -FilePath $exePath
Write-Host ("  Status        : {0}" -f $signature.Status)
if ($signature.SignerCertificate) {
  Write-Host ("  Subject       : {0}" -f $signature.SignerCertificate.Subject)
  Write-Host ("  NotAfter      : {0}" -f $signature.SignerCertificate.NotAfter)
  Write-Host ("  TimeStamper   : {0}" -f $signature.TimeStamperCertificate.Subject)
} else {
  Write-Host "  SignerCertificate: （无——包未签名）" 
}
Write-Host ("  预期结果：Status=Valid，Subject 为发布方证书，且存在可信时间戳") -ForegroundColor Magenta
if ($signature.Status -eq 'Valid') {
  Write-Ok "签名有效"
  Record '3.签名校验' 'PASS' ("Status=Valid Subject={0}" -f $signature.SignerCertificate.Subject)
} else {
  Write-Fail ("签名状态异常：{0}（历史审计曾发现公网 EXE 无 Authenticode 签名结构，必须阻断签字）" -f $signature.Status)
  Record '3.签名校验' 'FAIL' ("Status={0}" -f $signature.Status)
}
if (Confirm-Step "签名信息与上述一致且 Status=Valid" "签名校验结果无误？") { } else {
  Record '3.签名校验' 'FAIL' '人工确认不通过'
}

# ---------------------------------------------------------------- STEP 4 安装
Write-Step "4/7 安装（二选一，不影响现有安装）"
Write-Host "  方式 A：双击安装包，按提示完成（默认装到个人目录）；"
Write-Host ("  方式 B：静默安装到独立验收目录（推荐，命令如下）：") 
Write-Host ("      Start-Process -FilePath '{0}' -ArgumentList '/S','/D={1}' -Wait" -f $exePath, $AcceptRoot) -ForegroundColor White
Write-Host "      （/S 静默；/D= 自定义目录必须放最后、路径不含中文与空格）" 
$installChoice = Read-Host "  请选择执行方式 [A=我自己双击 / B=脚本帮我静默安装]"
if ($installChoice -match '^[Bb]') {
  Write-Info ("静默安装到 {0} ..." -f $AcceptRoot)
  $proc = Start-Process -FilePath $exePath -ArgumentList '/S', ("/D={0}" -f $AcceptRoot) -PassThru -Wait
  Write-Ok ("安装进程退出码：{0}" -f $proc.ExitCode)
} else {
  Write-Info "请现在双击安装包完成安装，完成后回到此窗口继续。"
}
if (Confirm-Step "开始菜单/桌面出现 XCAGI 图标，无安装报错弹窗" "安装是否完成且无报错？") {
  Record '4.安装' 'PASS' ("安装方式 {0}" -f $(if ($installChoice -match '^[Bb]') { '静默 /S' } else { '双击' }))
} else {
  Record '4.安装' 'FAIL' '人工报告安装失败或出现报错弹窗'
}

# ---------------------------------------------------------------- STEP 5 版本读取
Write-Step "5/7 安装版本核对"
$installRoot = Find-InstallRoot
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
    Record '5.版本核对' 'PASS' ("version={0} gitSha={1}" -f $buildInfo.version, $buildInfo.gitSha)
  } else {
    Record '5.版本核对' 'FAIL' ("build-info version={0} 与验收目标 {1} 不一致" -f $buildInfo.version, $Version)
  }
} else {
  Write-Fail "未找到包含 resources\build-info.json 的安装目录（候选：C:\XCAGI-acceptance、%LOCALAPPDATA%\Programs\XCAGI、%ProgramFiles%\XCAGI）"
  Record '5.版本核对' 'FAIL' '未定位到安装目录/build-info.json'
}
if ($installRoot -and (Confirm-Step "version 四段一致、sku 正确" "版本核对无误？")) { } elseif ($installRoot) {
  Record '5.版本核对' 'FAIL' '人工确认不通过'
}

# ---------------------------------------------------------------- STEP 6 冷启动
Write-Step "6/7 冷启动（计时 + 进程检测 + 健康检查）"
if ($SkipLaunch) {
  Write-Warn2 "已指定 -SkipLaunch：跳过真实启动。请在证据中注明「启动步骤以代码评审 + CI 冒烟替代」。"
  Record '6.冷启动' 'SKIP' '执行人指定跳过真实启动'
} else {
  $existing = Get-CimInstance Win32_Process -Filter "Name='XCAGI.exe'" -ErrorAction SilentlyContinue
  if ($existing) {
    foreach ($p in $existing) { Write-Host ("    已有实例: PID={0} Path={1}" -f $p.ProcessId, $p.ExecutablePath) }
    Write-Fail "检测到正在运行的 XCAGI 实例（单实例锁与 17500 端口会冲突）。请先完全退出（托盘右键 → 退出）后重跑，或改用 -SkipLaunch。"
    Record '6.冷启动' 'FAIL' '存在已运行实例，冷启动前置条件不满足'
  } else {
    $targetExe = if ($installRoot) { Join-Path $installRoot 'XCAGI.exe' } else { $null }
    if (-not ($targetExe -and (Test-Path $targetExe))) {
      Write-Fail ("找不到可启动的 XCAGI.exe：{0}" -f $targetExe)
      Record '6.冷启动' 'FAIL' 'XCAGI.exe 不存在'
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
        Record '6.冷启动' 'FAIL' '进程未出现'
      }

      Start-Sleep -Seconds 8
      $healthOk = $false
      for ($i = 0; $i -lt 60; $i++) {
        try { $health = Invoke-RestMethod -Uri $HealthUrl -TimeoutSec 3; $healthOk = $true; break }
        catch { Start-Sleep -Seconds 1 }
      }
      if ($healthOk) {
        Write-Ok ("健康检查通过：{0}" -f ($health | ConvertTo-Json -Compress -Depth 3))
        Record '6.冷启动' 'PASS' ("PID={0} health=healthy" -f $newProc.ProcessId)
      } else {
        Write-Fail ("健康检查 60 秒内未通过（{0}）" -f $HealthUrl)
        Record '6.冷启动' 'FAIL' 'health 未通过'
      }
      Write-Info "请现在对主窗口截图（PrtSc 或 Win+Shift+S），保存到证据目录 assets/ 后按 Y 继续。"
      if (Confirm-Step "截图已保存且主界面渲染完整（无白屏）" "主窗口截图与渲染确认？") { } else {
        Record '6.冷启动' 'FAIL' '人工报告白屏或渲染异常'
      }
    }
  }
}

# ---------------------------------------------------------------- STEP 7 OTA + 回滚（人工）
Write-Step "7/7 OTA 与回滚（人工执行，脚本只给指引）"
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
Record '7a.OTA' $(if ($otaResult) { $otaResult.ToUpper() } else { 'SKIP' }) $otaNote

Write-Host ""
Write-Host "▶ 回滚（协议第 5 节）：" -ForegroundColor Cyan
Write-Host "  路径 A（观察期自动回滚，需专用验收机构造坏更新）：更新后启动失败 → 自动还原旧版本；"
Write-Host ("     取证：Get-Content \"$env:APPDATA\XCAGI\rollback-applied.json\"（应含 reason/fromVersion/toVersion）")
Write-Host "  路径 B（降级安装）：从历史版本目录下载旧版 exe 覆盖安装，确认版本回到旧版且 health healthy。"
Write-Host "  ※ 未注入坏更新时记 PARTIAL，引用 rollback.test.ts + update-rollback.e2e.spec.ts 佐证。"
$rbResult = Read-Host "  回滚执行结果 [PASS/FAIL/PARTIAL/SKIP]"
$rbNote   = Read-Host "  回滚备注（方式/回滚后版本号/健康状态，一行）"
Record '7b.回滚' $(if ($rbResult) { $rbResult.ToUpper() } else { 'SKIP' }) $rbNote

# ---------------------------------------------------------------- 汇总
Write-Host ""
Write-Host ("=" * 72) -ForegroundColor DarkCyan
Write-Host (" 验收结果汇总（版本 {0} · Windows x64）" -f $Version) -ForegroundColor White
Write-Host ("=" * 72) -ForegroundColor DarkCyan
$script:Results | Format-Table -AutoSize | Out-Host
Write-Host "【证据归档】按模板逐项填写：" -ForegroundColor Yellow
Write-Host "  模板   ：FHD/docs/e2e/templates/desktop-acceptance-template.md"
Write-Host ("  另存为 ：FHD/docs/evidence/e2e/desktop-real-machine-acceptance-{0}-win10.md（或 win11）" -f $Version)
Write-Host "  截图   ：FHD/docs/evidence/e2e/assets/"
Write-Host ("  工作目录（含下载的安装包与 manifest）：{0}" -f $WorkDir)
Write-Host ("=" * 72) -ForegroundColor DarkCyan

$hasFail = @($script:Results | Where-Object { $_.结果 -eq 'FAIL' }).Count -gt 0
if ($hasFail) { Write-Host "结论：存在 FAIL 项 —— 该平台验收未闭环。" -ForegroundColor Red; exit 1 }
Write-Host "结论：本轮引导完成，无 FAIL 记录（以人工确认与证据文件为准）。" -ForegroundColor Green
exit 0
