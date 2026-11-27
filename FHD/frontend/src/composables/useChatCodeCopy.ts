import { onBeforeUnmount } from 'vue'

export async function writeChatClipboard(text: string): Promise<void> {
  const desktop = window.xcagiDesktop
  if (!desktop?.clipboardWriteText) return navigator.clipboard.writeText(text)
  if (!(await desktop.clipboardWriteText(text)).ok) throw new Error('Clipboard write failed')
}

/** Delegate copy clicks from sanitized Markdown in either chat surface. */
export function useChatCodeCopy() {
  let disposed = false
  const timers = new Set<number>()
  onBeforeUnmount(() => {
    disposed = true
    timers.forEach(timer => clearTimeout(timer))
  })

  return async (event: MouseEvent): Promise<void> => {
    const { currentTarget: host, target } = event
    if (disposed || !(host instanceof HTMLElement) || !(target instanceof Element)) return
    const button = target.closest<HTMLButtonElement>('.md-code__copy, [data-copy-source]')
    if (!button || !host.contains(button)) return
    event.stopPropagation()
    const source = button.hasAttribute('data-copy-source')
    const value = source ? button.closest<HTMLElement>('.md-mermaid')?.dataset.source
      : button.closest('.md-code')?.querySelector('.md-code__body')?.textContent
    const initial = button.textContent
    let label = '已复制'
    try { await writeChatClipboard(value || '') } catch { label = '复制失败' }
    if (disposed || !host.contains(button)) return
    button.textContent = label
    const timer = window.setTimeout(() => {
      timers.delete(timer)
      if (!disposed && host.contains(button)) button.textContent = initial || (source ? '复制源码' : '复制')
    }, 1400)
    timers.add(timer)
  }
}
