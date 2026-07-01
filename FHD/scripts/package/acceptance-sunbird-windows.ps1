param(
  [string]$BaseUrl = 'http://127.0.0.1:5000',
  [string]$Username = 'SUNBIRD',
  [string]$Password = 'SUN123456',
  [string]$DbWriteToken = $env:FHD_DB_WRITE_TOKEN,
  [string]$DbReadToken = $env:FHD_DB_READ_TOKEN,
  [string]$TutorialExcelPath = '',
  [string]$AttendanceInputPath = '',
  [string]$AttendanceTemplatePath = '',
  [string]$WorkDir = '',
  [int]$ReadyTimeoutSeconds = 180,
  [int]$MinHostFoundationCount = 10
)

$ErrorActionPreference = 'Stop'

$AcceptanceBaseUrl = 'https://xiu-ci.com/xcagi-v10.0.0/acceptance'
$TutorialExcelUrl = "$AcceptanceBaseUrl/xcagi-tutorial-dept-employee.xlsx"
$AttendanceInputUrl = "$AcceptanceBaseUrl/sunbird-attendance-input.xlsx"
$AttendanceTemplateUrl = "$AcceptanceBaseUrl/sunbird-attendance-template.xlsx"

if (-not $WorkDir) {
  $WorkDir = Join-Path $env:TEMP 'xcagi-sunbird-acceptance'
}
New-Item -ItemType Directory -Force -Path $WorkDir | Out-Null

$CookieJar = Join-Path $WorkDir 'cookies.txt'
Set-Content -Path $CookieJar -Value '' -Encoding ASCII

$script:PassCount = 0

function Join-XcagiUrl {
  param([Parameter(Mandatory = $true)][string]$Path)
  if ($Path.StartsWith('http://') -or $Path.StartsWith('https://')) {
    return $Path
  }
  return $BaseUrl.TrimEnd('/') + '/' + $Path.TrimStart('/')
}

function Invoke-XcagiJson {
  param(
    [Parameter(Mandatory = $true)][string]$Path,
    [ValidateSet('GET', 'POST')][string]$Method = 'GET',
    [object]$Body = $null,
    [string[]]$Form = @(),
    [int]$TimeoutSec = 60
  )

  $url = Join-XcagiUrl $Path
  $args = @(
    '-sS',
    '-L',
    '--max-time', [string]$TimeoutSec,
    '-b', $CookieJar,
    '-c', $CookieJar
  )

  if ($Form.Count -gt 0) {
    foreach ($entry in $Form) {
      $args += @('-F', $entry)
    }
  } elseif ($Method -eq 'POST') {
    $json = if ($null -eq $Body) { '{}' } else { $Body | ConvertTo-Json -Depth 64 -Compress }
    $args += @('-H', 'Content-Type: application/json', '--data-binary', $json)
  }

  $args += $url
  $output = & curl.exe @args 2>&1
  if ($LASTEXITCODE -ne 0) {
    throw "curl failed for $Path exit=$LASTEXITCODE output=$output"
  }
  $text = ($output | Out-String).Trim()
  if (-not $text) {
    throw "empty response from $Path"
  }
  try {
    return $text | ConvertFrom-Json
  } catch {
    throw "non-json response from $Path: $($text.Substring(0, [Math]::Min(300, $text.Length)))"
  }
}

function Get-EnvelopeData {
  param([object]$Payload)
  if ($Payload -and ($Payload.PSObject.Properties.Name -contains 'data')) {
    return $Payload.data
  }
  return $Payload
}

function Get-ResponseAction {
  param([object]$Payload)
  $data = Get-EnvelopeData $Payload
  if ($data -and ($data.PSObject.Properties.Name -contains 'action')) {
    return [string]$data.action
  }
  if ($data -and ($data.PSObject.Properties.Name -contains 'data')) {
    $inner = $data.data
    if ($inner -and ($inner.PSObject.Properties.Name -contains 'action')) {
      return [string]$inner.action
    }
  }
  return ''
}

function Get-ListTotal {
  param([object]$Payload)
  if ($Payload -and ($Payload.PSObject.Properties.Name -contains 'total')) {
    return [int]$Payload.total
  }
  $data = Get-EnvelopeData $Payload
  if ($data -and ($data.PSObject.Properties.Name -contains 'total')) {
    return [int]$data.total
  }
  if ($data -is [array]) {
    return [int]$data.Count
  }
  if ($data -and ($data.PSObject.Properties.Name -contains 'items') -and $data.items -is [array]) {
    return [int]$data.items.Count
  }
  return 0
}

function Assert-XlsxFile {
  param([Parameter(Mandatory = $true)][string]$Path)
  if (-not (Test-Path $Path)) {
    throw "file not found: $Path"
  }
  $fs = [System.IO.File]::OpenRead($Path)
  try {
    $buf = New-Object byte[] 2
    [void]$fs.Read($buf, 0, 2)
    if ($buf[0] -ne 0x50 -or $buf[1] -ne 0x4b) {
      throw "not an xlsx zip file: $Path"
    }
  } finally {
    $fs.Dispose()
  }
}

function Resolve-OrDownloadFile {
  param(
    [string]$GivenPath,
    [Parameter(Mandatory = $true)][string]$FileName,
    [Parameter(Mandatory = $true)][string]$Url
  )
  if ($GivenPath -and (Test-Path $GivenPath)) {
    $resolved = (Resolve-Path $GivenPath).Path
    Assert-XlsxFile $resolved
    return $resolved
  }
  $dest = Join-Path $WorkDir $FileName
  Invoke-WebRequest -Uri $Url -OutFile $dest -UseBasicParsing -TimeoutSec 120
  Assert-XlsxFile $dest
  return $dest
}

function Invoke-Check {
  param(
    [Parameter(Mandatory = $true)][string]$Name,
    [Parameter(Mandatory = $true)][scriptblock]$Body
  )
  try {
    $detail = & $Body
    $script:PassCount += 1
    Write-Host "PASS $Name $detail"
  } catch {
    Write-Host "FAIL $Name $($_.Exception.Message)"
    throw
  }
}

function Wait-XcagiReady {
  $deadline = (Get-Date).AddSeconds($ReadyTimeoutSeconds)
  while ((Get-Date) -lt $deadline) {
    try {
      $health = Invoke-XcagiJson '/api/health' -TimeoutSec 5
      if ($health) {
        return
      }
    } catch {
      Start-Sleep -Seconds 2
    }
  }
  throw "backend did not become ready: $BaseUrl/api/health"
}

function Select-ExcelSheet {
  param(
    [Parameter(Mandatory = $true)][object]$Analysis,
    [Parameter(Mandatory = $true)][string]$SheetName
  )
  $idx = 1
  $sheets = @($Analysis.sheets)
  for ($i = 0; $i -lt $sheets.Count; $i += 1) {
    if ([string]$sheets[$i].sheet_name -eq $SheetName) {
      $idx = if ($sheets[$i].sheet_index) { [int]$sheets[$i].sheet_index } else { $i + 1 }
      return @{ sheet_name = $SheetName; sheet_index = $idx }
    }
  }
  $names = @($Analysis.preview_data.sheet_names)
  for ($i = 0; $i -lt $names.Count; $i += 1) {
    if ([string]$names[$i] -eq $SheetName) {
      return @{ sheet_name = $SheetName; sheet_index = $i + 1 }
    }
  }
  throw "sheet not found: $SheetName"
}

function Invoke-ChatImport {
  param(
    [Parameter(Mandatory = $true)][object]$ExcelAnalysis,
    [Parameter(Mandatory = $true)][string]$SheetName,
    [Parameter(Mandatory = $true)][string]$Message,
    [Parameter(Mandatory = $true)][string]$UserId
  )
  $selected = Select-ExcelSheet -Analysis $ExcelAnalysis -SheetName $SheetName
  $context = [ordered]@{
    recent_messages = @()
    excel_analysis = $ExcelAnalysis
    excel_analysis_selected_sheet = $selected
    preferred_sheet_name = $selected.sheet_name
    preferred_sheet_index = $selected.sheet_index
    excel_import_use_deterministic_shortcut = $true
  }
  if ($DbWriteToken) {
    $context['chat_db_write_authorized'] = $true
  }
  $body = [ordered]@{
    message = $Message
    source = 'pro'
    mode = 'professional'
    user_id = $UserId
    context = $context
  }
  if ($DbWriteToken) {
    $body['db_write_token'] = $DbWriteToken
  }
  if ($DbReadToken) {
    $body['db_read_token'] = $DbReadToken
  }

  $resp = Invoke-XcagiJson '/api/ai/chat' -Method POST -Body $body -TimeoutSec 180
  if ($resp.requires_token -or (Get-EnvelopeData $resp).requires_token) {
    throw "chat import requires token: $((Get-EnvelopeData $resp).token_name)"
  }
  $action = Get-ResponseAction $resp
  if ($action -eq 'workflow_confirmation_required' -or ([string]$resp.response).Contains('回复「确认」')) {
    $confirm = [ordered]@{
      message = '确认'
      source = 'pro'
      mode = 'professional'
      user_id = $UserId
      context = $context
    }
    if ($DbWriteToken) {
      $confirm['db_write_token'] = $DbWriteToken
    }
    if ($DbReadToken) {
      $confirm['db_read_token'] = $DbReadToken
    }
    $resp = Invoke-XcagiJson '/api/ai/chat' -Method POST -Body $confirm -TimeoutSec 180
  }
  if (-not $resp.success) {
    throw "chat import failed: $($resp.message) $($resp.response)"
  }
  return ([string]$resp.response).Substring(0, [Math]::Min(120, ([string]$resp.response).Length))
}

Invoke-Check 'health' {
  Wait-XcagiReady
  'ready'
}

$tutorialPath = Resolve-OrDownloadFile $TutorialExcelPath 'xcagi-tutorial-dept-employee.xlsx' $TutorialExcelUrl
$attendanceInput = Resolve-OrDownloadFile $AttendanceInputPath 'sunbird-attendance-input.xlsx' $AttendanceInputUrl
$attendanceTemplate = Resolve-OrDownloadFile $AttendanceTemplatePath 'sunbird-attendance-template.xlsx' $AttendanceTemplateUrl

Invoke-Check 'login:SUNBIRD' {
  $login = Invoke-XcagiJson '/api/auth/login' -Method POST -Body @{
    username = $Username
    password = $Password
    account_kind = 'enterprise'
  } -TimeoutSec 90
  if (-not $login.success) {
    throw "login failed: $($login.message) $($login.error.message)"
  }
  $me = Invoke-XcagiJson '/api/auth/me' -TimeoutSec 30
  if (-not $me.success) {
    throw "auth/me failed: $($me.message)"
  }
  $data = Get-EnvelopeData $me
  if ([string]$data.user.username -ne $Username) {
    throw "logged in as $($data.user.username), expected $Username"
  }
  "username=$($data.user.username);account_kind=$($data.account_kind)"
}

Invoke-Check 'host-foundation:install' {
  $res = Invoke-XcagiJson '/api/mod-store/install-host-foundation?edition=full' -Method POST -Body @{} -TimeoutSec 180
  if (-not $res.success) {
    throw "host foundation failed: $($res.message)"
  }
  $data = Get-EnvelopeData $res
  $count = [int]$data.installed_count
  $expected = [int]$data.expected_count
  if (-not $data.ready) {
    throw "not ready: $($res.message)"
  }
  if ($count -lt $MinHostFoundationCount) {
    throw "installed_count=$count below minimum=$MinHostFoundationCount"
  }
  "installed=$count/$expected"
}

$workspaceRoot = ''
Invoke-Check 'workspace-template' {
  $wr = Invoke-XcagiJson '/api/platform-shell/workspace-root' -TimeoutSec 30
  $data = Get-EnvelopeData $wr
  $workspaceRoot = [string]$data.workspace_root
  if (-not $workspaceRoot) {
    throw 'missing workspace_root'
  }
  $targetDir = Join-Path $workspaceRoot '424'
  New-Item -ItemType Directory -Force -Path $targetDir | Out-Null
  $target = Join-Path $targetDir '考勤-2026-3月份考勤统计表.xlsx'
  Copy-Item -Path $attendanceTemplate -Destination $target -Force
  Assert-XlsxFile $target
  "template=$target"
}

$excelAnalysis = $null
Invoke-Check 'chat-excel:analyze' {
  $form = @(
    "file=@$tutorialPath",
    'analyze_all_sheets=true'
  )
  $excelAnalysis = Invoke-XcagiJson '/api/templates/extract-grid' -Method POST -Form $form -TimeoutSec 180
  if (-not $excelAnalysis.success) {
    throw "extract-grid failed"
  }
  $fp = [string]$excelAnalysis.file_path
  $wr = [string]$excelAnalysis.workspace_root
  if ($fp -and $wr -and -not [System.IO.Path]::IsPathRooted($fp)) {
    $abs = Join-Path $wr $fp
    $excelAnalysis | Add-Member -Force -NotePropertyName file_path -NotePropertyValue $abs
    if ($excelAnalysis.preview_data) {
      $excelAnalysis.preview_data | Add-Member -Force -NotePropertyName file_path -NotePropertyValue $abs
    }
  }
  $sheets = @($excelAnalysis.preview_data.sheet_names)
  if (-not ($sheets -contains '教程示例-部门') -or -not ($sheets -contains '教程示例-人员')) {
    throw "unexpected sheets: $($sheets -join ',')"
  }
  "sheets=$($sheets -join ',')"
}

$chatUserId = 'sunbird_acceptance_' + [guid]::NewGuid().ToString('N').Substring(0, 8)
Invoke-Check 'chat-import:departments' {
  Invoke-ChatImport -ExcelAnalysis $excelAnalysis -SheetName '教程示例-部门' -Message '导入数据库，类型客户，确认导入' -UserId $chatUserId
}

Invoke-Check 'chat-import:employees' {
  Invoke-ChatImport -ExcelAnalysis $excelAnalysis -SheetName '教程示例-人员' -Message '导入数据库，类型产品，确认导入' -UserId $chatUserId
}

Invoke-Check 'db-verify:departments' {
  $kw = [System.Uri]::EscapeDataString('教程示例-')
  $res = Invoke-XcagiJson "/api/customers/list?page=1&per_page=50&keyword=$kw" -TimeoutSec 60
  $total = Get-ListTotal $res
  if ($total -lt 2) {
    throw "expected at least 2 tutorial departments/customers, got $total"
  }
  "total=$total"
}

Invoke-Check 'db-verify:employees' {
  $kw = [System.Uri]::EscapeDataString('教程示例-')
  $res = Invoke-XcagiJson "/api/products/list?page=1&per_page=50&keyword=$kw" -TimeoutSec 60
  $total = Get-ListTotal $res
  if ($total -lt 3) {
    throw "expected at least 3 tutorial employees/products, got $total"
  }
  "total=$total"
}

Invoke-Check 'attendance:convert-upload' {
  $form = @(
    "file=@$attendanceInput",
    'output_relpath=424/sunbird-acceptance-attendance-output.xlsx',
    'template_relpath=424/考勤-2026-3月份考勤统计表.xlsx',
    'month=2025-10',
    'header_row=0',
    'use_llm=0',
    'use_personnel_roster=0'
  )
  $res = Invoke-XcagiJson '/api/mod/taiyangniao-pro/attendance/convert-upload' -Method POST -Form $form -TimeoutSec 240
  if (-not $res.success) {
    throw "attendance conversion failed: $($res.error) $($res.message)"
  }
  $data = Get-EnvelopeData $res
  if ([int]$data.rows_in -le 0 -or [int]$data.rows_stats -le 0) {
    throw "bad conversion rows: rows_in=$($data.rows_in);rows_stats=$($data.rows_stats)"
  }
  $out = [string]$data.output_path
  if ($out -and -not (Test-Path $out)) {
    throw "output path missing on disk: $out"
  }
  "rows_in=$($data.rows_in);rows_stats=$($data.rows_stats);output=$($data.output_relpath)"
}

Write-Host "ACCEPTANCE_PASS=1"
Write-Host "ACCEPTANCE_CHECKS=$script:PassCount"
