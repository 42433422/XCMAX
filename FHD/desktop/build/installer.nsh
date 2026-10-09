!define XCAGI_PRODUCT_DISPLAY_VERSION "1.0.0.5"

!macro customHeader
  BrandingText "${PRODUCT_NAME} ${XCAGI_PRODUCT_DISPLAY_VERSION}"
!macroend

!macro XcagiResolvePowerShell
  ; 32-bit NSIS cannot trust IfFileExists on Sysnative. RunningX64 + Sysnative
  ; reaches 64-bit PowerShell; the script itself also works if this falls through.
  ${If} ${RunningX64}
    StrCpy $R9 "$WINDIR\Sysnative\WindowsPowerShell\v1.0\powershell.exe"
  ${Else}
    StrCpy $R9 "$WINDIR\System32\WindowsPowerShell\v1.0\powershell.exe"
  ${EndIf}
!macroend

!macro customInstall
  WriteRegStr SHELL_CONTEXT "${UNINSTALL_REGISTRY_KEY}" "DisplayVersion" "${XCAGI_PRODUCT_DISPLAY_VERSION}"

  DetailPrint "Registering XCAGI backup scheduled tasks..."
  !insertmacro XcagiResolvePowerShell
  nsExec::ExecToLog '"$R9" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$INSTDIR\resources\backend\_internal\scripts\backup\Install-BackupTask.ps1"'
  Pop $0
  ${If} $0 != 0
    DetailPrint "WARNING: backup task registration exited with code $0. Installation continues."
  ${Else}
    DetailPrint "XCAGI backup scheduled tasks registered."
  ${EndIf}
!macroend

!macro customUnInstall
  DetailPrint "Removing XCAGI backup scheduled tasks..."
  !insertmacro XcagiResolvePowerShell
  nsExec::ExecToLog '"$R9" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$INSTDIR\resources\backend\_internal\scripts\backup\Uninstall-BackupTask.ps1"'
  Pop $0
  DetailPrint "XCAGI backup scheduled tasks cleanup done (exit code $0)."
!macroend
