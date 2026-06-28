/// <reference types="vite/client" />

declare module '*.vue' {
  import type { DefineComponent } from 'vue'
  const component: DefineComponent
  export default component
}

interface ImportMetaEnv {
  readonly VITE_PUBLIC_BASE?: string
  readonly VITE_API_PROXY_TARGET?: string
  readonly VITE_MODSTORE_CATALOG_UPLOAD_TOKEN?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}

interface Window {
  readonly xcagiDesktop?: {
    readonly isDesktop?: boolean
    readonly platform?: string
    readonly version?: string
    readonly downloadFile?: (payload: {
      url: string
      filename: string
    }) => Promise<{ ok?: boolean; canceled?: boolean; filePath?: string; filename?: string; error?: string }>
  }
}
