# 停止本机常见开发进程，减少「文件被占用 / Python OSError 22」类写入失败。
# 用法（PowerShell）:  cd E:\FHD ; .\scripts\stop-dev-and-unlock.ps1
# 需要管理员时：以管理员打开 PowerShell 再执行（仅在使用 openfiles 排查时）。

$ErrorActionPreference = 'SilentlyContinue'

$names = @(
  'node', 'node.exe',
  'esbuild', 'esbuild.exe',
  'vite', 'vite.exe',
  'uvicorn', 'uvicorn.exe',
  'python', 'python.exe', 'pythonw', 'pythonw.exe'
)

Write-Host '[stop-dev] Killing common dev processes (if any)...'
foreach ($n in $names) {
  Get-Process -Name $n -ErrorAction SilentlyContinue | ForEach-Object {
    Write-Host "  Stop PID $($_.Id) $($_.ProcessName)"
    Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
  }
}

Start-Sleep -Seconds 1
Write-Host '[stop-dev] Done. Retry save / build / agent edit.'
Write-Host '[hint] If a file still cannot be written:'
Write-Host '  1) Close the tab preview for that file in the editor.'
Write-Host '  2) Pause OneDrive / antivirus real-time scan on E:\FHD (temporarily).'
Write-Host '  3) Task Manager -> Details: end leftover node.exe / Code.exe child processes.'
