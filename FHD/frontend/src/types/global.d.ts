// 全局变量声明
declare global {
  interface Window {
    __VUE_APP_ACTIVE__: boolean;
    __VUE_CHAT_OWNS_INPUT__: boolean;
    __VUE_CHAT_FILL__?: (prefix: string) => boolean;
    __legacyToggleProMode?: () => void;
    toggleProMode?: () => void;
    __XCAGI_IS_PRO_MODE?: boolean;
    setProModeEnabled: (enabled: boolean) => void;
    openImportWindow?: () => void;
    isProTaskAcquisitionMessage?: (text: string) => boolean;
    setWorkModeFromChat?: (enabled: boolean) => void;
    setMonitorModeFromChat?: (enabled: boolean) => void;
    refreshWorkModeMonitorList?: () => void;
    legacyAutoActionHandler?: (action: Record<string, unknown>, userMessage: string) => void;
    jarvisSendMessage?: (message: string) => void;
  }
}

export {};
