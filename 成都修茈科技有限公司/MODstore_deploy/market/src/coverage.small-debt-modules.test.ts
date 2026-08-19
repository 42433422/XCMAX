import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  
  CORP_BALL_STORAGE,
  getCorpDefaultBallPosition,
  isContactPagePath,
  loadCorpBallPosition,
  saveCorpBallPosition,
} from './corp-butler/corpBallPosition'
import { composeTicketUserMessage, toUserFacingCards } from './utils/csTicketSummary'
import { prefetchSubtitleTranslations, translateZhToEn } from './utils/ttsSubtitleTranslate'

describe('ticket summary user language', () => {
  const ticket = { intent: 'refund', ticket_no: 'TICKET-123456789', status: 'processing' }

  it('covers missing information, failed, completed and pending action outcomes', () => {
    expect(composeTicketUserMessage({
      ticket,
      decision: { decision: 'needs_more_info', rationale: '请补充 order_no 和 reason' },
    })).toContain('订单号')
    expect(composeTicketUserMessage({
      ticket,
      actions: [{ action_type: 'refund.apply', status: 'failed' }],
    })).toContain('处理没有成功')
    expect(composeTicketUserMessage({
      ticket,
      actions: [
        { action_type: 'refund.apply', status: 'completed' },
        { action_type: 'refund.apply', status: 'skipped' },
      ],
    })).toContain('已办妥（退款申请）')
    expect(composeTicketUserMessage({
      ticket,
      actions: [{ action_type: 'employee.dispatch', status: 'failed' }],
    })).toContain('值班员工仍在跟进')
  })

  it('covers lifecycle fallbacks and hides internal rationale/cards', () => {
    expect(composeTicketUserMessage({
      ticket: { ...ticket, status: 'closed' },
      decision: { rationale: '审核标准允许低风险动作自动受理' },
    })).toContain('已处理完成')
    expect(composeTicketUserMessage({
      ticket: { ...ticket, status: 'processing' },
      decision: { decision: 'accepted', rationale: '合规审核队列已写入审计' },
    })).toContain('已进入审核')
    expect(composeTicketUserMessage({
      ticket: { intent: 'general', lifecycle_label: '自定义阶段' },
    })).toContain('自定义阶段')
    expect(toUserFacingCards([{ internal: true }])).toEqual([])
  })
})

describe('subtitle translation transport', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('short-circuits empty/English text, parses nested responses and caches results', async () => {
    expect(await translateZhToEn('')).toBe('')
    expect(await translateZhToEn('This sentence is already English')).toContain('already English')
    vi.mocked(fetch).mockResolvedValueOnce(new Response(JSON.stringify({
      data: { translation: 'Hello, world.' },
    }), { status: 200 }))
    expect(await translateZhToEn('你好世界')).toBe('Hello, world.')
    expect(await translateZhToEn('你好世界')).toBe('Hello, world.')
    expect(fetch).toHaveBeenCalledOnce()
  })

  it('fails open for HTTP, empty payload and network errors', async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(new Response('{}', { status: 503 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ text: '' }), { status: 200 }))
      .mockRejectedValueOnce(new Error('offline'))
    expect(await translateZhToEn('服务不可用')).toBe('')
    expect(await translateZhToEn('没有翻译结果')).toBe('')
    expect(await translateZhToEn('网络中断')).toBe('')
  })

  it('prefetches lines concurrently and respects abort signals', async () => {
    vi.mocked(fetch).mockImplementation(async (_url, init) => {
      const body = JSON.parse(String(init?.body)) as { text: string }
      return new Response(JSON.stringify({ en: `EN:${body.text}` }), { status: 200 })
    })
    const lines: Array<[number, string]> = []
    prefetchSubtitleTranslations(['第一句', '', '第二句'], (index, en) => lines.push([index, en]), {
      concurrency: 3,
    })
    await flushPromises()
    expect(lines).toEqual(expect.arrayContaining([[0, 'EN:第一句'], [2, 'EN:第二句']]))

    const controller = new AbortController()
    controller.abort()
    prefetchSubtitleTranslations(['不会发送'], vi.fn(), { signal: controller.signal })
    await flushPromises()
  })
})

describe('corporate floating ball positioning', () => {
  let mobile = false

  beforeEach(() => {
    localStorage.clear()
    mobile = false
    vi.stubGlobal('matchMedia', vi.fn(() => ({
      matches: mobile,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })))
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 1200 })
    Object.defineProperty(window, 'innerHeight', { configurable: true, value: 800 })
    window.history.replaceState({}, '', '/')
  })

  afterEach(() => vi.unstubAllGlobals())

  it('uses desktop, contact and mobile defaults and clamps saved coordinates', () => {
    expect(isContactPagePath()).toBe(false)
    expect(getCorpDefaultBallPosition()).toEqual({ x: 1112, y: 688 })
    window.history.replaceState({}, '', '/contact.html')
    expect(isContactPagePath()).toBe(true)
    expect(getCorpDefaultBallPosition().x).toBe(16)
    window.history.replaceState({}, '', '/')
    mobile = true
    expect(getCorpDefaultBallPosition().x).toBe(16)
    expect(saveCorpBallPosition(-100, 9000)).toEqual({ x: 8, y: 704 })
  })

  it('loads valid positions and repairs malformed, obstructive or mobile-overlap values', () => {
    localStorage.setItem(CORP_BALL_STORAGE, JSON.stringify({ x: 900, y: 500 }))
    expect(loadCorpBallPosition()).toEqual({ x: 900, y: 500 })

    localStorage.setItem(CORP_BALL_STORAGE, JSON.stringify({ x: 20, y: 20 }))
    expect(loadCorpBallPosition()).toEqual(getCorpDefaultBallPosition())

    localStorage.setItem(CORP_BALL_STORAGE, 'not-json')
    expect(loadCorpBallPosition()).toEqual(getCorpDefaultBallPosition())

    mobile = true
    localStorage.setItem(CORP_BALL_STORAGE, JSON.stringify({ x: 1190, y: 790 }))
    expect(loadCorpBallPosition().x).toBe(16)
  })
})
