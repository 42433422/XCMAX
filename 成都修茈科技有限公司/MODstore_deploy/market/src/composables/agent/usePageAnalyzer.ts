import { serializeVisibleDom } from '../../utils/agent/pageSerializer'
import { useRoute } from 'vue-router'

export function usePageAnalyzer() {
  const route = useRoute()

  function getPageContext(): string {
    const dom = serializeVisibleDom()
    return `路由：${route.fullPath}\n${dom}`
  }

  async function getPageContextWithScreenshot(): Promise<{
    textSummary: string
    screenshotDataUrl: string | null
  }> {
    const textSummary = getPageContext()
    const { captureViewport } = await import('../../utils/agent/screenshotCapture')
    const screenshotDataUrl = await captureViewport()
    return { textSummary, screenshotDataUrl }
  }

  return { getPageContext, getPageContextWithScreenshot }
}
