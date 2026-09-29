!define XCAGI_PRODUCT_DISPLAY_VERSION "1.0.0.5"

; XCAGI NSIS include. build-installer.ps1 rewrites XCAGI_PRODUCT_DISPLAY_VERSION
; from VERSION.md before electron-builder runs. npm/Electron stay on the
; three-part toolchain version; the uninstall DisplayVersion is the four-part
; product version.

!macro customInstall
  WriteRegStr SHELL_CONTEXT "${UNINSTALL_REGISTRY_KEY}" "DisplayVersion" "${XCAGI_PRODUCT_DISPLAY_VERSION}"

  DetailPrint "Registering XCAGI backup scheduled tasks..."
  StrCpy $R9 "$WINDIR\Sysnative\WindowsPowerShell\v1.0\powershell.exe"
  ${IfNot} ${FileExists} "$R9"
    StrCpy $R9 "$WINDIR\System32\WindowsPowerShell\v1.0\powershell.exe"
  ${EndIf}
  nsExec::ExecToLog '"$R9" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$INSTDIR\resources\backend\_internal\scripts\backup\Install-BackupTask.ps1"'
  Pop $0
  ${If} $0 != 0
    DetailPrint "ERROR: backup task registration exited with code $0"
    MessageBox MB_ICONSTOP "XCAGI backup scheduled task registration failed (exit $0). Backup is not delivered."
    Abort
  ${Else}
    DetailPrint "XCAGI backup scheduled tasks registered."
  ${EndIf}
!macroend

!macro customUnInstall
  DetailPrint "Removing XCAGI backup scheduled tasks..."
  StrCpy $R9 "$WINDIR\Sysnative\WindowsPowerShell\v1.0\powershell.exe"
  ${IfNot} ${FileExists} "$R9"
    StrCpy $R9 "$WINDIR\System32\WindowsPowerShell\v1.0\powershell.exe"
  ${EndIf}
  nsExec::ExecToLog '"$R9" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$INSTDIR\resources\backend\_internal\scripts\backup\Uninstall-BackupTask.ps1"'
  Pop $0
  DetailPrint "XCAGI backup scheduled tasks cleanup done (exit code $0)."
!macroend
