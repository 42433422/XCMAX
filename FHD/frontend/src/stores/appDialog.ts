import { defineStore } from 'pinia';
import { ref } from 'vue';

export type AppDialogKind = 'alert' | 'confirm' | 'prompt';

export interface AppDialogConfirmOptions {
  title?: string;
  danger?: boolean;
  confirmText?: string;
  cancelText?: string;
}

export interface AppDialogAlertOptions {
  title?: string;
}

export interface AppDialogPromptOptions {
  title?: string;
  confirmText?: string;
  cancelText?: string;
  placeholder?: string;
}

export const useAppDialogStore = defineStore('appDialog', () => {
  const visible = ref(false);
  const kind = ref<AppDialogKind>('alert');
  const title = ref('提示');
  const message = ref('');
  const confirmText = ref('确定');
  const cancelText = ref('取消');
  const danger = ref(false);
  const promptPlaceholder = ref('');
  const promptInput = ref('');

  const queue: Array<() => void> = [];
  let currentResolve: ((value: unknown) => void) | null = null;

  function runNext() {
    const next = queue.shift();
    if (next) next();
  }

  function finish(value: unknown) {
    const r = currentResolve;
    visible.value = false;
    currentResolve = null;
    if (r) r(value);
    runNext();
  }

  function enqueue(open: () => void) {
    if (visible.value) {
      queue.push(open);
    } else {
      open();
    }
  }

  function showAlert(msg: string, options?: AppDialogAlertOptions): Promise<void> {
    return new Promise((resolve) => {
      enqueue(() => {
        kind.value = 'alert';
        title.value = options?.title?.trim() || '提示';
        message.value = msg;
        confirmText.value = '确定';
        cancelText.value = '取消';
        danger.value = false;
        promptPlaceholder.value = '';
        promptInput.value = '';
        currentResolve = () => resolve();
        visible.value = true;
      });
    });
  }

  function showConfirm(msg: string, options?: AppDialogConfirmOptions): Promise<boolean> {
    return new Promise((resolve) => {
      enqueue(() => {
        kind.value = 'confirm';
        title.value = options?.title?.trim() || '确认';
        message.value = msg;
        confirmText.value = options?.confirmText?.trim() || '确定';
        cancelText.value = options?.cancelText?.trim() || '取消';
        danger.value = options?.danger ?? false;
        promptPlaceholder.value = '';
        promptInput.value = '';
        currentResolve = (v) => resolve(Boolean(v));
        visible.value = true;
      });
    });
  }

  function showPrompt(
    msg: string,
    defaultValue = '',
    options?: AppDialogPromptOptions
  ): Promise<string | null> {
    return new Promise((resolve) => {
      enqueue(() => {
        kind.value = 'prompt';
        title.value = options?.title?.trim() || '输入';
        message.value = msg;
        confirmText.value = options?.confirmText?.trim() || '确定';
        cancelText.value = options?.cancelText?.trim() || '取消';
        danger.value = false;
        promptPlaceholder.value = options?.placeholder?.trim() || '';
        promptInput.value = defaultValue ?? '';
        currentResolve = (v) => resolve(v === undefined ? null : (v as string | null));
        visible.value = true;
      });
    });
  }

  function ackAlert() {
    finish(undefined);
  }

  function ackConfirm(ok: boolean) {
    finish(ok);
  }

  function ackPrompt(submit: boolean) {
    if (submit) {
      finish(promptInput.value);
    } else {
      finish(null);
    }
  }

  return {
    visible,
    kind,
    title,
    message,
    confirmText,
    cancelText,
    danger,
    promptPlaceholder,
    promptInput,
    showAlert,
    showConfirm,
    showPrompt,
    ackAlert,
    ackConfirm,
    ackPrompt,
  };
});
