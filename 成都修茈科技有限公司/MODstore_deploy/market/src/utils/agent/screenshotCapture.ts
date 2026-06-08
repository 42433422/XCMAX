/** 懒加载 html2canvas 并截取当前视口，返回 base64 data URL */
export async function captureViewport(): Promise<string | null> {
  try {
    const { default: html2canvas } = await import('html2canvas')
    const canvas = await html2canvas(document.body, {
      scale: 0.5,
      useCORS: true,
      logging: false,
      ignoreElements: (el: Element) => {
        // 忽略管家自身悬浮层
        return el.classList.contains('butler-float-root')
      },
    })
    return canvas.toDataURL('image/jpeg', 0.7)
  } catch {
    return null
  }
}
