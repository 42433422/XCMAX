# 微信同步代理开机自启安装脚本（Windows，管理员 PowerShell 运行）
# 用法：
#   安装：powershell -ExecutionPolicy Bypass -File .\wechat_sync_install_task.ps1
#   卸载：powershell -ExecutionPolicy Bypass -File .\wechat_sync_install_task.ps1 -Remove
# 行为：注册当前用户登录触发计划任务「XCAGI WeChat Sync」，执行 wechat_sync_start.bat；
#       进程异常退出由任务设置自动重启（最多 999 次，间隔 1 分钟），批处理层另有 60 秒兜底重启。

param([switch]$Remove)

$ErrorActionPreference = "Stop"
$taskName = "XCAGI WeChat Sync"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$batPath = Join-Path $scriptDir "wechat_sync_start.bat"

if ($Remove) {
    if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
        Write-Host "[wechat_sync] 已卸载计划任务: $taskName"
    } else {
        Write-Host "[wechat_sync] 任务不存在，无需卸载"
    }
    exit 0
}

if (-not (Test-Path $batPath)) {
    Write-Error "[wechat_sync] 未找到 $batPath"
    exit 1
}

$action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$batPath`"" -WorkingDirectory $scriptDir
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal -Force | Out-Null

Write-Host "[wechat_sync] 计划任务已注册: $taskName（下次登录自动运行；立即测试请运行 Start-ScheduledTask -TaskName '$taskName'）"
Write-Host "[wechat_sync] 排障：日志在同目录 wechat_sync.log；配置见 wechat_sync_config.json"
