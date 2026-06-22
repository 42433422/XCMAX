import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useContactCompanyMatch } from './useContactCompanyMatch'

const bridgeState = vi.hoisted(() => ({
  selectAiCompany: vi.fn(),
}))

vi.mock('./contactIntakeBridge', () => ({
  getBridge: () => ({ selectAiCompany: bridgeState.selectAiCompany }),
}))

function jsonResponse(data: unknown) {
  return new Response(JSON.stringify(data), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
}

async function flushMatchTimer() {
  await vi.advanceTimersByTimeAsync(401)
  await Promise.resolve()
}

function installHiddenCompanyInput() {
  const hidden = document.createElement('input')
  hidden.id = 'intake-ai-company'
  document.body.appendChild(hidden)
  return hidden
}

beforeEach(() => {
  vi.useFakeTimers()
  bridgeState.selectAiCompany.mockReset()
  vi.stubGlobal('fetch', vi.fn())
})

afterEach(() => {
  document.body.innerHTML = ''
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

describe('useContactCompanyMatch branch coverage', () => {
  it('covers contact no-match warnings and non-ok service statuses', async () => {
    const fetchMock = vi.mocked(fetch)
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ found: false, web_error: 'timeout' }))
      .mockResolvedValueOnce(jsonResponse({ found: false, suggestions: [] }))
      .mockResolvedValueOnce(new Response('', { status: 404 }))
      .mockResolvedValueOnce(new Response('', { status: 500 }))

    const webError = useContactCompanyMatch('contact')
    webError.unlockMatchUi()
    webError.onCompanyInput('成都修茈科技有限公司', () => '成都修茈科技有限公司')
    await flushMatchTimer()
    expect(webError.resultText.value).toContain('联网检索暂不可用')
    expect(webError.hint.value).toContain('稍后重试')

    const noMatch = useContactCompanyMatch('contact')
    noMatch.unlockMatchUi()
    noMatch.onCompanyInput('成都修茈科技有限公司', () => '成都修茈科技有限公司')
    await flushMatchTimer()
    expect(noMatch.resultText.value).toContain('未匹配到该公司')
    expect(noMatch.hint.value).toContain('补全公司全称')

    const missingApi = useContactCompanyMatch('contact')
    missingApi.unlockMatchUi()
    missingApi.onCompanyInput('成都修茈科技有限公司', () => '成都修茈科技有限公司')
    await flushMatchTimer()
    expect(missingApi.resultText.value).toBe('匹配服务暂时不可用')
    expect(missingApi.hint.value).toContain('xiu-ci.com')

    const serverDown = useContactCompanyMatch('contact')
    serverDown.unlockMatchUi()
    serverDown.onCompanyInput('成都修茈科技有限公司', () => '成都修茈科技有限公司')
    await flushMatchTimer()
    expect(serverDown.resultText.value).toBe('匹配服务暂时不可用')
    expect(serverDown.hint.value).toContain('稍后重试')
  })

  it('covers workbench matched hints, multi-pick results, null payloads, and contact selection sync', async () => {
    const hidden = installHiddenCompanyInput()
    const fetchMock = vi.mocked(fetch)
    fetchMock
      .mockResolvedValueOnce(jsonResponse({
        found: true,
        web_used: true,
        matched: { name: '成都修茈科技有限公司', source: 'web' },
        suggestions: [],
      }))
      .mockResolvedValueOnce(jsonResponse({
        found: true,
        matched: { name: '成都修茈科技有限公司', source: 'crm' },
        suggestions: [],
      }))
      .mockResolvedValueOnce(jsonResponse({
        found: true,
        matched: { name: '成都修茈科技有限公司', source: 'web' },
        suggestions: [
          { name: '成都修茈科技有限公司' },
          { name: '成都修茈科技服务有限公司' },
        ],
      }))
      .mockResolvedValueOnce(jsonResponse(null))

    const webMatched = useContactCompanyMatch('workbench')
    webMatched.onCompanyInput('成都修茈科技有限公司', () => '成都修茈科技有限公司')
    await flushMatchTimer()
    expect(webMatched.hint.value).toContain('联网检索核对')
    expect(webMatched.hintVariant.value).toBe('ok')

    const crmMatched = useContactCompanyMatch('workbench')
    crmMatched.onCompanyInput('成都修茈科技有限公司', () => '成都修茈科技有限公司')
    await flushMatchTimer()
    expect(crmMatched.hint.value).toContain('历史记录')

    const multiPick = useContactCompanyMatch('contact')
    multiPick.unlockMatchUi()
    multiPick.onCompanyInput('成都修茈科技', () => '成都修茈科技')
    await flushMatchTimer()
    expect(multiPick.resolvedName.value).toBe('')
    expect(multiPick.showSuggestions.value).toBe(true)
    expect(multiPick.hint.value).toContain('搜索词仍保留')

    const nullPayload = useContactCompanyMatch('workbench')
    nullPayload.onCompanyInput('成都修茈科技有限公司', () => '成都修茈科技有限公司')
    await flushMatchTimer()
    expect(nullPayload.resultMode.value).toBe('hidden')
    expect(nullPayload.hint.value).toBe('')

    const picked = useContactCompanyMatch('contact')
    await picked.selectSuggestion({ name: '成都修茈科技有限公司 | 企查查' }, ' 成都修茈 ')
    expect(picked.hint.value).toContain('系统类型')
    expect(hidden.value).toBe('成都修茈')
    expect(bridgeState.selectAiCompany).toHaveBeenCalledWith(expect.objectContaining({
      name: '成都修茈科技有限公司',
      exact: true,
    }))
  })

  it('covers debounce clearing, cached payload reuse, and unlocked same-query hints', async () => {
    const fetchMock = vi.mocked(fetch)
    fetchMock.mockResolvedValueOnce(jsonResponse({
      found: true,
      matched: { name: '成都修茈科技有限公司', source: 'crm' },
      suggestions: [],
    }))

    const matcher = useContactCompanyMatch('contact')
    matcher.unlockMatchUi()
    matcher.onCompanyInput('成都修茈科技有限公司', () => '成都修茈科技有限公司')
    matcher.onCompanyInput('成都修茈科技有限公司', () => '成都修茈科技有限公司')
    await flushMatchTimer()

    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(matcher.resolvedName.value).toBe('成都修茈科技有限公司')
    expect(matcher.hint.value).toContain('已匹配')

    matcher.onCompanyInput('成都修茈科技有限公司', () => '成都修茈科技有限公司')
    expect(matcher.hint.value).toContain('点选')

    matcher.onIndustryFocus(() => '成都修茈科技有限公司')
    matcher.onIndustryFocus(() => '成都修茈科技有限公司')
    await flushMatchTimer()

    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(matcher.resolvedName.value).toBe('成都修茈科技有限公司')
  })
})
