// 全局变量声明
declare global {
  interface Window {
    __VUE_APP_ACTIVE__: boolean
    __VUE_CHAT_FILL__?: (prefix: string) => boolean
    openImportWindow?: () => void
    legacyAutoActionHandler?: (action: Record<string, unknown>, userMessage: string) => void
  }
}

export {}
