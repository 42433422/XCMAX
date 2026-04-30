$sh = New-Object -ComObject WScript.Shell
$lnk = $sh.CreateShortcut('C:\Users\97088\Desktop\start-lan.bat - 快捷方式.lnk')
Write-Host "TargetPath:        $($lnk.TargetPath)"
Write-Host "Arguments:         $($lnk.Arguments)"
Write-Host "WorkingDirectory:  $($lnk.WorkingDirectory)"
Write-Host "WindowStyle:       $($lnk.WindowStyle)"
Write-Host "IconLocation:      $($lnk.IconLocation)"
Write-Host "Description:       $($lnk.Description)"
Write-Host "TargetExists:      $(Test-Path $lnk.TargetPath)"
