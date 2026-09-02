import { ref } from 'vue'

/** 右下角轻提示：3 秒自动消失，同类型新消息重置计时器 */
export function useTmToast() {
  const toastMessage = ref('')
  const toastType = ref<'success' | 'error'>('success')
  let toastTimer: number | null = null

  function showToast(message: string, type: 'success' | 'error' = 'success') {
    toastMessage.value = message
    toastType.value = type
    if (toastTimer) clearTimeout(toastTimer)
    toastTimer = window.setTimeout(() => { toastMessage.value = '' }, 3000)
  }

  function disposeToast() {
    if (toastTimer) clearTimeout(toastTimer)
  }

  return { toastMessage, toastType, showToast, disposeToast }
}
