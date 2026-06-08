/** 同步 visualViewport 底部占用（浏览器底栏 / 软键盘）到 CSS 变量 */
export function installVisualViewportInset() {
  if (typeof window === 'undefined') return () => {}

  const sync = () => {
    const vv = window.visualViewport
    if (!vv) {
      document.documentElement.style.setProperty('--wb-vv-bottom-offset', '0px')
      return
    }
    const bottomInset = Math.max(0, window.innerHeight - vv.height - vv.offsetTop)
    document.documentElement.style.setProperty('--wb-vv-bottom-offset', `${bottomInset}px`)
  }

  sync()
  window.visualViewport?.addEventListener('resize', sync)
  window.visualViewport?.addEventListener('scroll', sync)
  window.addEventListener('resize', sync)

  return () => {
    window.visualViewport?.removeEventListener('resize', sync)
    window.visualViewport?.removeEventListener('scroll', sync)
    window.removeEventListener('resize', sync)
    document.documentElement.style.setProperty('--wb-vv-bottom-offset', '0px')
  }
}
