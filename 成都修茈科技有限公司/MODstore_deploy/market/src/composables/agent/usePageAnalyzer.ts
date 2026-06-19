import { serializeVisibleDom } from '../../utils/agent/pageSerializer'
import { useRoute } from 'vue-router'

export function usePageAnalyzer() {
  const route = useRoute()

  function getPageContext(): string {
    const dom = serializeVisibleDom()
    return `路由：${route.fullPath}\n${dom}`
  }

  async function getPageContextWithScreenshot(options: { screenshot?: any } = {}): Promise<{
    textSummary: string
    screenshotDataUrl: string | null
  }> {
    const textSummary = getPageContext()
    const { captureViewport } = await import('../../utils/agent/screenshotCapture')
    const screenshot = await captureViewport(options.screenshot)
  const screenshotDataUrl = screenshot.ok ? screenshot.dataUrl : null
    return { textSummary, screenshot, screenshotDataUrl }
  }

  return { getPageContext, getPageContextWithScreenshot }
}
