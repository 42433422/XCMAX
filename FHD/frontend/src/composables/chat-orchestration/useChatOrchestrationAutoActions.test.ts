import { afterEach, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import { flushPromises } from '@vue/test-utils'
import { useChatOrchestrationAutoActions } from './useChatOrchestrationAutoActions'

afterEach(() => vi.unstubAllGlobals())

it.each([true, false])('forwards product UI to the main renderer and reports its actual receipt: %s', async ok => {
  let reply!: (value: { ok: boolean }) => void
  const openProducts = vi.fn(() => new Promise<{ ok: boolean }>(resolve => { reply = resolve }))
  vi.stubGlobal('xcagiDesktopAssistant', { openProducts })
  const latestAssistantPush = ref<{ title: string; description: string } | null>(null)
  const { handleAutoAction } = useChatOrchestrationAutoActions({ latestAssistantPush, tutorialStore: {} as never })
  const orphanedEvent = vi.fn()
  window.addEventListener('xcagi:open-assistant-float', orphanedEvent)
  try {
    handleAutoAction({ type: 'show_products_float', query: ' part-42 ', hydrateProductSearch: { rows: [{ private: true }] } })
    expect(openProducts).toHaveBeenCalledExactlyOnceWith('part-42')
    expect(latestAssistantPush.value).toBeNull()
    expect(orphanedEvent).not.toHaveBeenCalled()
    reply({ ok })
    await flushPromises()
    expect(latestAssistantPush.value?.description).toContain(ok ? '已在主窗口打开' : '未能打开')
  } finally { window.removeEventListener('xcagi:open-assistant-float', orphanedEvent) }
})
