$ErrorActionPreference = 'Stop'

$lnkPath    = 'C:\Users\97088\Desktop\start-lan.bat - ' + [char]0x5FEB + [char]0x6377 + [char]0x65B9 + [char]0x5F0F + '.lnk'
$targetBat  = 'E:\FHD\scripts\launchers\start-lan.bat'
$workingDir = 'E:\FHD'
$iconSrc    = "$env:SystemRoot\System32\cmd.exe"

if (-not (Test-Path -LiteralPath $targetBat)) {
    throw ("target batch missing: " + $targetBat)
}

if (Test-Path -LiteralPath $lnkPath) {
    Remove-Item -LiteralPath $lnkPath -Force
}

$sh  = New-Object -ComObject WScript.Shell
$lnk = $sh.CreateShortcut($lnkPath)
$lnk.TargetPath       = $targetBat
$lnk.Arguments        = ''
$lnk.WorkingDirectory = $workingDir
$lnk.WindowStyle      = 1
$lnk.Description      = 'XCAGI LAN launcher'
$lnk.IconLocation     = ($iconSrc + ',0')
$lnk.Save()

# Flip the RunAsAdmin bit in the .lnk header (byte 21 = 0x15)
$bytes = [System.IO.File]::ReadAllBytes($lnkPath)
$bytes[21] = $bytes[21] -bor 0x20
[System.IO.File]::WriteAllBytes($lnkPath, $bytes)

$verify = $sh.CreateShortcut($lnkPath)
Write-Host ("TargetPath       : " + $verify.TargetPath)
Write-Host ("Arguments        : '" + $verify.Arguments + "'")
Write-Host ("WorkingDirectory : " + $verify.WorkingDirectory)
Write-Host ("IconLocation     : " + $verify.IconLocation)
Write-Host ("TargetExists     : " + (Test-Path -LiteralPath $verify.TargetPath))
Write-Host ("LnkExists        : " + (Test-Path -LiteralPath $lnkPath))
