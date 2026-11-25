import { test, expect, type Page, type TestInfo } from '@playwright/test'
import { writeFileSync } from 'node:fs'
import { installStartupReadinessMocks } from '../e2e/startup-readiness-fixture'
import { latencyPercentile } from '../e2e/performance-budget'

const sourceSha = process.env.SOURCE_SHA || ''
const navBudget = 200
const frameBudget = 1000 / 60
const iterations = 30

function distribution(samples: number[]) {
  return { samples_ms: samples, count: samples.length,
    p50_ms: samples.length >= 20 ? latencyPercentile(samples, 50) : null,
    p95_ms: samples.length >= 20 ? latencyPercentile(samples, 95) : null }
}

function record(info: TestInfo, data: Record<string, unknown>) {
  writeFileSync(info.outputPath('measurements.json'), JSON.stringify({
    source_sha: sourceSha, browser: info.project.use.browserName,
    viewport: info.project.use.viewport, node: process.version,
    scope: 'production Chromium renderer, synthetic desktop bridge/account; not native Electron or Flutter',
    ...data,
  }, null, 2))
}

async function setup(page: Page, baseURL: string) {
  await page.route('**/*', route => new URL(route.request().url()).origin === baseURL
    ? route.continue() : route.abort('blockedbyclient'))
  await page.routeWebSocket('**/*', socket => socket.close())
  return installStartupReadinessMocks(page)
}

async function ready(page: Page) {
  const start = Date.now()
  await page.goto('/', { waitUntil: 'domcontentloaded' })
  await expect(page.locator('.app-shell.is-ready')).toBeVisible({ timeout: 30000 })
  await expect(page.locator('#messageInput')).toBeVisible()
  await expect(page.getByTestId('startup-readiness')).toHaveCount(0)
  expect(sourceSha).toMatch(/^[0-9a-f]{40}$/)
  expect(await page.locator('meta[name="xcmax-release-git-sha"]').getAttribute('content')).toBe(sourceSha)
  return Date.now() - start
}

// Measure in the renderer clock, not Playwright polling or an artificial delay.
// Two animation frames with the destination visible and not busy are a paint proxy.
async function navigation(page: Page, destination: 'settings' | 'chat') {
  const button = destination === 'settings'
    ? await page.locator('.top-bar-settings-btn').elementHandle()
    : null
  try {
    return await page.evaluate(({ destination, button }) => new Promise<number>((resolve, reject) => {
      const start = performance.now()
      let consecutive = 0
      let frame = 0
      const timeout = window.setTimeout(() => {
        cancelAnimationFrame(frame)
        reject(new Error('destination not ready: ' + destination))
      }, 10000)
      const tick = () => {
        const target = document.querySelector(destination === 'settings' ? '#view-settings' : '#messageInput')
        const rect = target?.getBoundingClientRect()
        const path = destination === 'settings' ? '/settings' : '/'
        const usable = location.pathname === path && !!rect && rect.width > 0 && rect.height > 0
          && document.querySelector('.route-content')?.getAttribute('aria-busy') !== 'true'
        consecutive = usable ? consecutive + 1 : 0
        if (consecutive >= 2) {
          clearTimeout(timeout)
          resolve(performance.now() - start)
        } else frame = requestAnimationFrame(tick)
      }
      if (destination === 'settings') (button as HTMLElement).click()
      else history.back()
      frame = requestAnimationFrame(tick)
    }), { destination, button })
  } finally { await button?.dispose() }
}

test('cold shell, cold settings and warm route paint proxy', async ({ page, baseURL }, info) => {
  const { calls } = await setup(page, new URL(baseURL!).origin)
  const toSettings: number[] = [], toChat: number[] = []
  const requests: Record<string, number>[] = []
  let startup: number | null = null, coldSettings: number | null = null, coldBack: number | null = null
  try {
    startup = await ready(page)
    coldSettings = await navigation(page, 'settings')
    coldBack = await navigation(page, 'chat')
    for (let i = 0; i < iterations; i++) {
      const before = new Map(calls)
      toSettings.push(await navigation(page, 'settings'))
      toChat.push(await navigation(page, 'chat'))
      requests.push(Object.fromEntries([...calls].map(([key, n]) => [key, n - (before.get(key) || 0)]).filter(([, n]) => Number(n) > 0)))
    }
    expect(toSettings).toHaveLength(iterations)
    expect(toChat).toHaveLength(iterations)
  } finally {
    record(info, { scenario: 'local synthetic API, cold and warm separated', startup_runner_wall_ms: startup,
      cold_settings_ms: coldSettings, cold_history_back_ms: coldBack,
      settings_click: distribution(toSettings), history_back: distribution(toChat),
      target_p95_ms: navBudget, api_call_counts_per_roundtrip: requests,
      settings_target_met: toSettings.length === iterations ? latencyPercentile(toSettings, 95) <= navBudget : null,
      history_target_met: toChat.length === iterations ? latencyPercentile(toChat, 95) <= navBudget : null })
  }
})

test('timed SSE through the existing chat runtime and real message DOM', async ({ page, baseURL }, info) => {
  await setup(page, new URL(baseURL!).origin)
  // Synthetic transport only: no production network or model inference is measured.
  await page.addInitScript(() => {
    const state = { request: 0, firstEnqueue: 0, lastEnqueue: 0, done: 0, tokens: 0, firstPaint: 0, finalPaint: 0, frameIntervals: [] as number[], sendClick: 0 }
    Object.assign(window, { __xcmaxUiPerf: state })
    const original = window.fetch.bind(window)
    window.fetch = (input, init) => {
      const url = new URL(input instanceof Request ? input.url : String(input), location.href)
      const method = init?.method || (input instanceof Request ? input.method : 'GET')
      if (url.pathname !== '/api/ai/chat/stream' || method.toUpperCase() !== 'POST') return original(input, init)
      state.request = performance.now()
      const signal = init?.signal || (input instanceof Request ? input.signal : undefined)
      const encoder = new TextEncoder()
      const chunks = ['XCMAXBENCHSTART\n\n', ...Array.from({ length: 240 }, (_, i) => '- 固定数据项 ' + i + '\n'), '\nXCMAXBENCHEND']
      const response = chunks.join('')
      let index = 0, timer = 0
      let closed = false
      let detach = () => {}
      const body = new ReadableStream<Uint8Array>({
        start(controller) {
          const close = () => {
            if (closed) return
            closed = true
            clearTimeout(timer)
            detach()
            controller.close()
          }
          const abort = () => close()
          signal?.addEventListener('abort', abort, { once: true })
          detach = () => signal?.removeEventListener('abort', abort)
          const emit = (event: object) => controller.enqueue(encoder.encode('data: ' + JSON.stringify(event) + '\n\n'))
          const send = () => {
            if (closed) return
            if (signal?.aborted) { close(); return }
            for (let n = 0; n < 2 && index < chunks.length; n++) {
              if (!state.firstEnqueue) state.firstEnqueue = performance.now()
              emit({ type: 'token', text: chunks[index++] })
              state.tokens++
              state.lastEnqueue = performance.now()
            }
            if (index === chunks.length) {
              state.done = performance.now()
              emit({ type: 'done', result: { success: true, response } })
              close()
            } else timer = window.setTimeout(send, 16)
          }
          timer = window.setTimeout(send, 16)
        },
        cancel() { closed = true; clearTimeout(timer); detach() },
      })
      return Promise.resolve(new Response(body, { status: 200, headers: { 'Content-Type': 'text/event-stream' } }))
    }
    document.addEventListener('click', event => {
      if (!(event.target instanceof Element) || !event.target.closest('#sendMessageBtn')) return
      if (state.sendClick) return
      state.sendClick = performance.now()
      let previous = 0
      const tick = (now: number) => {
        if (previous && state.firstEnqueue && !state.finalPaint) state.frameIntervals.push(now - previous)
        previous = now
        const bubbles = document.querySelectorAll('#chatMessages .message.ai .message-html')
        const content = bubbles[bubbles.length - 1]?.textContent || ''
        if (!state.firstPaint && content.includes('XCMAXBENCHSTART')) state.firstPaint = performance.now()
        if (content.includes('XCMAXBENCHEND')) state.finalPaint = performance.now()
        if (!state.finalPaint && now - state.sendClick < 30000) requestAnimationFrame(tick)
      }
      requestAnimationFrame(tick)
    }, true)
  })
  try {
    await ready(page)
    await page.locator('#messageInput').fill('请用 Markdown 详细介绍库存管理流程，仅解释概念，不执行任务。')
    await page.locator('#sendMessageBtn').click()
    await expect(page.locator('#chatMessages .message.ai .message-html').last()).toContainText('XCMAXBENCHEND', { timeout: 30000 })
    await page.waitForFunction(() => (window as any).__xcmaxUiPerf.finalPaint > 0)
    await expect(page.getByTestId('stop-reply')).toHaveCount(0, { timeout: 10000 })
    const s = await page.evaluate(() => (window as any).__xcmaxUiPerf)
    expect(s.tokens).toBe(242)
    expect(s.firstEnqueue).toBeGreaterThan(s.request)
    expect(s.firstPaint).toBeGreaterThanOrEqual(s.firstEnqueue)
    expect(s.firstPaint).toBeLessThan(s.done)
    expect(s.frameIntervals.length).toBeGreaterThanOrEqual(20)
  } finally {
    const s = await page.evaluate(() => (window as any).__xcmaxUiPerf || null).catch(() => null)
    record(info, { scenario: 'timed synthetic SSE, actual parser and Vue DOM', raw: s,
      input_to_request_ms: s?.request && s?.sendClick ? s.request - s.sendClick : null,
      fixture_wait_ms: s?.firstEnqueue && s?.request ? s.firstEnqueue - s.request : null,
      first_token_to_visible_frame_ms: s?.firstPaint && s?.firstEnqueue ? s.firstPaint - s.firstEnqueue : null,
      frame_intervals: distribution(s?.frameIntervals || []),
      frame_budget_ms: frameBudget, network_ms: null, model_inference_ms: null })
  }
})
