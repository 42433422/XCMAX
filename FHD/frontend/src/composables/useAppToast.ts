import { ElMessage, ElNotification } from 'element-plus';
import type { MessageHandler } from 'element-plus';

export type AppToastLevel = 'success' | 'error' | 'warning' | 'info';

export interface AppToastOptions {
  duration?: number;
  showClose?: boolean;
}

export function showAppToast(
  message: string,
  level: AppToastLevel = 'error',
  options: AppToastOptions = {},
): MessageHandler {
  const text = String(message || '').trim();
  return ElMessage({
    message: text || ' ',
    type: level,
    duration: options.duration ?? 3200,
    showClose: options.showClose ?? true,
  });
}

export function showAppNotification(title: string, body: string): void {
  ElNotification({
    title: String(title || '通知'),
    message: String(body || ''),
    duration: 4500,
  });
}

export function useAppToast() {
  return { showAppToast, showAppNotification };
}
