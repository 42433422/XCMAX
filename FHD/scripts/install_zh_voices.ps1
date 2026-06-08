# FHD 一键安装 Windows 中文语音包
# 用法：右键 → 使用 PowerShell 运行（需要管理员）；或由 FHD 后端通过 Start-Process -Verb RunAs 调起
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}
try { chcp 65001 | Out-Null } catch {}

Write-Host ''
Write-Host '==============================================='
Write-Host '  FHD 一键安装 Windows 中文神经网络语音'
Write-Host '==============================================='
Write-Host ''

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host '✗ 当前不是管理员，无法安装系统语音包。请右键以管理员身份运行本脚本。' -ForegroundColor Red
    Read-Host '按回车键关闭'
    exit 1
}

try {
    Write-Host '[1/2] 扫描 zh-CN 语音相关组件...'
    $all = Get-WindowsCapability -Online | Where-Object {
        $_.Name -like 'Language.Speech~*zh-CN*' -or
        $_.Name -like 'Language.TextToSpeech~*zh-CN*' -or
        $_.Name -like 'Language.Basic~*zh-CN*'
    }

    if ($null -eq $all -or $all.Count -eq 0) {
        Write-Host '当前系统镜像未列出 zh-CN 语音 capability，可能是 Windows 版本较旧。' -ForegroundColor Yellow
        Write-Host '建议改用 FHD 顶栏“下载离线包”走本地 MMS-TTS 合成。'
        Read-Host '按回车键关闭'
        exit 0
    }

    Write-Host ''
    Write-Host '检测到的组件：'
    $all | Select-Object Name, State | Format-Table -AutoSize | Out-String | Write-Host

    $pending = $all | Where-Object { $_.State -ne 'Installed' }
    if ($null -eq $pending -or $pending.Count -eq 0) {
        Write-Host '✓ zh-CN 语音组件已是最新，无需安装。' -ForegroundColor Green
        Write-Host ''
        Write-Host '如果 FHD 聊天顶栏仍提示未检测到云希/晓晓：'
        Write-Host '  1) 关闭 FHD 浏览器标签再打开（语音列表会在启动时重新加载）。'
        Write-Host '  2) 云希/晓晓 需 Windows 11 22H2+ 自然语音，可在 设置 → 辅助功能 → 讲述人 → 添加自然语音 里补装。'
        Read-Host '按回车键关闭'
        exit 0
    }

    Write-Host ''
    Write-Host ('[2/2] 需要安装：' + $pending.Count + ' 个') -ForegroundColor Cyan
    foreach ($cap in $pending) {
        Write-Host ('  → ' + $cap.Name) -ForegroundColor Cyan
        Add-WindowsCapability -Online -Name $cap.Name | Out-Null
    }
    Write-Host ''
    Write-Host '✓ 安装完成！请关闭 FHD 浏览器标签页后重新打开，即可听到系统云希/晓晓。' -ForegroundColor Green
} catch {
    Write-Host ''
    Write-Host ('✗ 安装失败：' + $_.Exception.Message) -ForegroundColor Red
    Write-Host ''
    Write-Host '建议改用 FHD 顶栏“下载离线包”按钮，走本地 MMS-TTS 合成。'
}

Write-Host ''
Read-Host '按回车键关闭此窗口'
