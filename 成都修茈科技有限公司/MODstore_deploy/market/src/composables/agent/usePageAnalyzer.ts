import { serializeVisibleDom } from '../../utils/agent/pageSerializer'
import { redactForLLM } from '../../utils/agent/redactForLLM'
import { useRoute } from 'vue-router'
import type { CaptureOptions } from '../../utils/agent/screenshotCapture'

export function usePageAnalyzer() {
  const route = useRoute()

  function getPageContext(options: { redact?: boolean } = {}): string {
    const dom = serializeVisibleDom()
    const context = `路由：${route.fullPath}\n${dom}`
    return options.redact === false ? context : redactForLLM(context)
  }

  async function getPageContextWithScreenshot(options: { screenshot?: CaptureOptions } = {}) {
    const textSummary = getPageContext({ redact: true })
    const { captureViewport } = await import('../../utils/agent/screenshotCapture')
    const screenshot = await captureViewport(options.screenshot)
    const screenshotDataUrl = screenshot.ok ? screenshot.dataUrl : null
    return { textSummary, screenshot, screenshotDataUrl }
  }

  return { getPageContext, getPageContextWithScreenshot }
}
