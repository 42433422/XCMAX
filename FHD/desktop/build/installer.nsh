!define XCAGI_PRODUCT_DISPLAY_VERSION "1.0.0.5"

!ifndef nsProcess::FindProcess
  !include "nsProcess.nsh"
!endif

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

; Block upgrade while XCAGI (main window or tray) is still running.
; Prefer refuse-until-quit over killing the process or deleting locked user data
; (e.g. %APPDATA%\XCAGI\data\neuro_health_events.db). Never delete the DB.
!macro customCheckAppRunning
  StrCpy $R1 0
  xcagi_check_app_running:
    ${nsProcess::FindProcess} "${APP_EXECUTABLE_FILENAME}" $R0
    ${If} $R0 == 0
      ; Process still running (includes tray-only). Do not kill; ask user to quit.
      DetailPrint "XCAGI still running: ${APP_EXECUTABLE_FILENAME} holds open files under %APPDATA%\XCAGI (may include data\neuro_health_events.db). Installer will not delete the database or userData."
      ; Abort = cancel install; Retry = re-check after user quits; Ignore = show technical detail then re-prompt.
      MessageBox MB_ABORTRETRYIGNORE|MB_ICONEXCLAMATION|MB_TOPMOST \
        "旧版 XCAGI 仍在运行，请先退出软件（包括右下角托盘图标），再重试安装。$\r$\n$\r$\n不会删除数据库或用户数据。$\r$\n$\r$\n【重试】退出软件后继续检查$\r$\n【忽略】查看技术详情$\r$\n【中止】取消安装" \
        /SD IDABORT IDRETRY xcagi_check_app_running IDIGNORE xcagi_show_tech_detail
      ; Abort (or silent default): leave app running, do not delete data, quit installer.
      ${nsProcess::Unload}
      SetErrorLevel 2
      Quit

      xcagi_show_tech_detail:
        MessageBox MB_OK|MB_ICONINFORMATION \
          "技术详情$\r$\n$\r$\nDetected running process: ${APP_EXECUTABLE_FILENAME}$\r$\nTypical locked path: %APPDATA%\XCAGI\data\neuro_health_events.db$\r$\nCause: share violation while the previous XCAGI instance (window or system tray) is still open.$\r$\n$\r$\nAction: quit XCAGI completely (tray icon → 退出), then click Retry.$\r$\nThe installer never deletes neuro_health_events.db or userData to unlock files."
        Goto xcagi_check_app_running
    ${Else}
      ${nsProcess::Unload}
    ${EndIf}
!macroend

!macro customInstall
  WriteRegStr SHELL_CONTEXT "${UNINSTALL_REGISTRY_KEY}" "DisplayVersion" "${XCAGI_PRODUCT_DISPLAY_VERSION}"

  DetailPrint "Registering XCAGI backup scheduled tasks..."
  !insertmacro XcagiResolvePowerShell
  nsExec::ExecToLog '"$R9" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$INSTDIR\resources\backend\_internal\scripts\backup\Install-BackupTask.ps1" -DataDir "$APPDATA\XCAGI"'
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
