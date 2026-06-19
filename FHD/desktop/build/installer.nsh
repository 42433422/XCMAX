; XCAGI NSIS 安装包自定义脚本
; =============================================================================
; 此文件由 electron-builder 的 nsis.include 加载，可定义自定义宏覆盖安装行为。
; 文档: https://electron.build/configuration/nsis#custom-nsis-script
;
; 当前使用 electron-builder 默认安装流程，无需自定义宏。
; 如需添加自定义安装步骤（注册协议、写入注册表、安装后启动服务等），
; 在此处定义对应宏，例如:
;
;   !macro customInstall
;     WriteRegStr HKCU "Software\XCAGI" "InstallPath" "$INSTDIR"
;   !macroend
;
;   !macro customUnInstall
;     DeleteRegKey HKCU "Software\XCAGI"
;   !macroend
