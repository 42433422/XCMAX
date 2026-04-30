import { useAppDialogStore } from '@/stores/appDialog';
import type {
  AppDialogAlertOptions,
  AppDialogConfirmOptions,
  AppDialogPromptOptions,
} from '@/stores/appDialog';

/** 应用内提示（替代 window.alert），始终可用 await */
export function appAlert(message: string, options?: AppDialogAlertOptions): Promise<void> {
  return useAppDialogStore().showAlert(message, options);
}

/** 应用内确认（替代 window.confirm），返回是否点击确定 */
export function appConfirm(message: string, options?: AppDialogConfirmOptions): Promise<boolean> {
  return useAppDialogStore().showConfirm(message, options);
}

/** 应用内输入（替代 window.prompt），取消返回 null */
export function appPrompt(
  message: string,
  defaultValue?: string,
  options?: AppDialogPromptOptions
): Promise<string | null> {
  return useAppDialogStore().showPrompt(message, defaultValue ?? '', options);
}
