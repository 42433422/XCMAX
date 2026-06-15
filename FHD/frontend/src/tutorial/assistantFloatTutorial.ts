/** 教程收尾时收起顶栏助手副窗，避免挡住后续步骤 */
export function closeAssistantFloatPanelForTutorial(): void {
  if (typeof document === 'undefined') return
  const panel = document.querySelector('[data-tutorial-spotlight="assistant-panel"]')
  if (!panel) return

  const closeBtn =
    document.querySelector<HTMLElement>('[data-tour="assistant-float-close"]') ||
    document.querySelector<HTMLElement>('.assistant-float-panel .assistant-close')
  if (closeBtn) {
    closeBtn.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }))
    return
  }

  const toggle = document.querySelector<HTMLElement>('[data-tour="assistant-float-toggle"]')
  if (toggle?.getAttribute('aria-expanded') === 'true') {
    toggle.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }))
  }
}

export function isAssistantFloatPanelOpen(): boolean {
  if (typeof document === 'undefined') return false
  return Boolean(document.querySelector('[data-tutorial-spotlight="assistant-panel"]'))
}
