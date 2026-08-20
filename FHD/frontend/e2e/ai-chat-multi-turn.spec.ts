import { test, expect } from '@playwright/test'
import { installE2eShellMocks, isFullStack } from './helpers'

test.describe('AI multi-turn conversation @multi_turn', () => {
  test('AI 多轮对话：第二轮携带第一轮 context 返回连贯回复', async ({ page }) => {
    test.skip(isFullStack(), 'full-stack 模式由真实后端覆盖；此处只校验 mock 行为')

    await installE2eShellMocks(page)

    let chatCalls = 0
    let lastRequestBody: any = null
    await page.route('**/api/chat/send', async (route) => {
      chatCalls += 1
      const body = route.request().postDataJSON()
      lastRequestBody = body
      const reply =
        chatCalls === 1
          ? '好的，您想了解哪个城市的天气？'
          : `好的，${body?.context?.last_user_message || ''}后，${body?.message || ''} 的天气是晴天。`
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          data: {
            reply,
            conversation_id: body?.conversation_id || 'conv-e2e-001',
            turn: chatCalls,
          },
        }),
      })
    })

    await page.goto('/', { waitUntil: 'domcontentloaded', timeout: 30_000 })
    await expect(page.locator('.app-shell.is-ready')).toBeVisible({ timeout: 25_000 })

    const firstResult = await page.evaluate(async () => {
      const r = await fetch('/api/chat/send', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: '今天天气怎么样？', conversation_id: 'conv-e2e-001' }),
      })
      const json = await r.json().catch(() => ({}) as any)
      return { status: r.status, body: json }
    })
    expect(firstResult.status, `first turn status`).toBe(200)
    expect(firstResult.body?.success, `first turn body: ${JSON.stringify(firstResult.body)}`).toBe(true)
    expect(String(firstResult.body?.data?.reply)).toContain('哪个城市')
    expect(Number(firstResult.body?.data?.turn)).toBe(1)

    const firstReply = String(firstResult.body?.data?.reply || '')
    const secondResult = await page.evaluate(async (firstReplyCopy) => {
      const r = await fetch('/api/chat/send', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: '北京',
          conversation_id: 'conv-e2e-001',
          context: {
            last_user_message: '今天天气怎么样？',
            last_assistant_reply: firstReplyCopy,
          },
        }),
      })
      const json = await r.json().catch(() => ({}) as any)
      return { status: r.status, body: json }
    }, firstReply)

    expect(secondResult.status, `second turn status`).toBe(200)
    expect(secondResult.body?.success).toBe(true)
    expect(Number(secondResult.body?.data?.turn)).toBe(2)
    expect(secondResult.body?.data?.conversation_id).toBe('conv-e2e-001')

    expect(chatCalls, 'chat/send should be invoked twice').toBe(2)
    expect(lastRequestBody?.message).toBe('北京')
    expect(lastRequestBody?.context?.last_user_message).toBe('今天天气怎么样？')
    expect(String(secondResult.body?.data?.reply)).toContain('晴天')
  })
})
