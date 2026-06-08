#requires -Version 5.1
<#
.SYNOPSIS
  将远程 PostgreSQL 备份恢复到本地 Postgres（与 docker-compose 默认 modstore 库对齐）。

.DESCRIPTION
  依赖：本机已安装 PostgreSQL 客户端（pg_dump / pg_restore），且 PATH 可调用。
  本地库默认：postgresql://modstore:modstore@127.0.0.1:5432/modstore
  请先：docker compose -f docker-compose.yml up -d postgres

  安全：仅从你有权限的库导出（建议使用 staging / 只读副本）；勿向他人泄露连接串。

.PARAMETER RemoteUrl
  远程库连接 URI，例如 postgresql://user:pass@host:5432/modstore

.PARAMETER LocalUrl
  本地库连接 URI，默认与 Compose 中 postgres 服务一致（端口映射到宿主机 5432）。

.EXAMPLE
  .\scripts\sync_local_db_from_remote.ps1 -RemoteUrl 'postgresql://readonly:***@db.example.com:5432/modstore'
#>
param(
    [Parameter(Mandatory = $true)]
    [string] $RemoteUrl,

    [string] $LocalUrl = 'postgresql://modstore:modstore@127.0.0.1:5432/modstore'
)

$ErrorActionPreference = 'Stop'

function Test-Cmd([string]$Name) {
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

if (-not (Test-Cmd 'pg_dump') -or -not (Test-Cmd 'pg_restore')) {
    Write-Error @'
未找到 pg_dump / pg_restore。请安装 PostgreSQL 客户端工具并加入 PATH，
或从 https://www.postgresql.org/download/windows/ 安装 Command Line Tools。
'@
}

$dumpFile = Join-Path $env:TEMP ("modstore_sync_{0:yyyyMMdd_HHmmss}.dump" -f (Get-Date))

Write-Host "==> 导出远程库 -> $dumpFile"
& pg_dump @('--dbname', $RemoteUrl, '--format=custom', '--file', $dumpFile, '--no-owner')
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "==> 清空并恢复到本地库（--clean --if-exists）"
Write-Host "    本地: $LocalUrl"
$confirm = Read-Host "确认覆盖本地数据库? [y/N]"
if ($confirm -notmatch '^[yY]') {
    Remove-Item -Force $dumpFile -ErrorAction SilentlyContinue
    Write-Host "已取消。"
    exit 1
}

& pg_restore @('--dbname', $LocalUrl, '--clean', '--if-exists', '--no-owner', '--no-acl', '--verbose', $dumpFile) 2>&1 | ForEach-Object { $_ }
$restoreExit = $LASTEXITCODE
# pg_restore 常以 1 退出表示部分无关警告，但仍可能成功；此处仅记录
Write-Host "pg_restore exit code: $restoreExit"

Remove-Item -Force $dumpFile -ErrorAction SilentlyContinue

Write-Host @'

完成。请在 MODstore_deploy/.env.local 中设置：
  DATABASE_URL=postgresql://modstore:modstore@127.0.0.1:5432/modstore
并注释掉 MODSTORE_DB_PATH（若存在）。重启 API 后前端将通过代理访问本地一致的数据。
'@
