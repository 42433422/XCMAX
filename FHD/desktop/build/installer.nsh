; XCAGI NSIS 安装包自定义脚本
; =============================================================================
; 此文件由 electron-builder 的 nsis.include 加载，可定义自定义宏覆盖安装行为。
; 文档: https://electron.build/configuration/nsis#custom-nsscript
;
; 自定义安装步骤：
;   - customInstall：安装完成后注册 SQLite 定时备份 Windows 计划任务
;     （每日 12:30 + 每周日 12:30，满足灾备硬约束）
;   - customUnInstall：卸载时删除备份计划任务
;
; 备份脚本随 backend PyInstaller 包一同分发到 resources\backend\scripts\backup\，
; 由 NSIS 安装时调用 PowerShell 注册。

!macro customInstall
  ; 注册定时备份计划任务（幂等，重复安装不会重复注册）
  ; 备份脚本随 PyInstaller datas 打包到 _internal\scripts\backup\
  DetailPrint "Registering XCAGI backup scheduled tasks..."
  nsExec::ExecToLog 'powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$INSTDIR\resources\backend\_internal\scripts\backup\Install-BackupTask.ps1"'
  Pop $0
  ${If} $0 != 0
    DetailPrint "WARNING: backup task registration exited with code $0 (non-fatal)"
  ${Else}
    DetailPrint "XCAGI backup scheduled tasks registered."
  ${EndIf}
!macroend

!macro customUnInstall
  ; 卸载时清理计划任务
  DetailPrint "Removing XCAGI backup scheduled tasks..."
  nsExec::ExecToLog 'powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$INSTDIR\resources\backend\_internal\scripts\backup\Uninstall-BackupTask.ps1"'
  Pop $0
  DetailPrint "XCAGI backup scheduled tasks cleanup done (exit code $0)."
!macroend
