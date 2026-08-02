/// <reference types="vite/client" />

declare module '*.vue' {
  import type { DefineComponent } from 'vue';
  const component: DefineComponent<Record<string, never>, Record<string, never>, unknown>;
  export default component;
}

interface Window {
  xcagiDesktop?: {
    platform: NodeJS.Platform;
    versions: Record<string, string>;
    getAppIdentity?: () => Promise<{
      name?: string;
      version?: string;
      isPackaged?: boolean;
      install?: {
        appPath?: string | null;
        canonicalAppPath?: string | null;
        isCanonical?: boolean;
        canSelfUpdate?: boolean;
        reason?: string;
      };
    }>;
    getDataDir: () => Promise<string>;
    checkForUpdates: () => Promise<unknown>;
    getUpdateStatus?: () => Promise<{ type: string; data?: unknown } | null>;
    downloadUpdate: () => Promise<unknown>;
    installUpdate: () => Promise<void>;
    onUpdateEvent: (callback: (event: unknown) => void) => () => void;
    getPairingQrPayload?: () => Promise<string>;
    showNotification: (title: string, body: string) => Promise<void>;
    setBadge: (count: number) => Promise<void>;
  };
  handleAutoAction?: (action: unknown, userMessage?: string) => void;
}
