import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { usePhoneAgentPolling, type PhoneAgentPollingDeps } from './usePhoneAgentPolling'

const fetchMock = vi.fn()
beforeEach(() => { vi.useFakeTimers(); vi.setSystemTime(1000); vi.stubGlobal('fetch', fetchMock); fetchMock.mockReset() })
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks() })
function setup() {
  const deps = {
    getModsForUi: () => [{ id: 'phone-mod', workflow_employees: ['enabled', 'disabled', 'missing'].map((id) => ({ id, label: id, phone_agent_base_path: id })) }] as ReturnType<PhoneAgentPollingDeps['getModsForUi']>,
    readWorkflowEmployeeEnabledMap: vi.fn(() => ({ enabled: true, disabled: false, missing: true })),
    resolveWorkflowEmployeePanelMeta: (id: string) => id === 'missing' ? null : { title: id, summary: id },
    onStatusUpdate: vi.fn(), resolvePhoneChannelByEmployee: vi.fn(() => 'adb' as const),
    getPhoneAgentApiBase: vi.fn(() => '/api/mod/phone/'),
  }
  return { deps, poll: usePhoneAgentPolling(deps) }
}
function reply(body: unknown, status = 200) {
  fetchMock.mockResolvedValueOnce(new Response(typeof body === 'string' ? body : JSON.stringify(body), { status }))
}

describe('phone agent polling and recovery', () => {
  it('filters disabled employees and missing metadata, and avoids undeclared endpoints', async () => {
    const { deps, poll } = setup()
    expect(poll.getEnabledPhoneEmployeeIds()).toEqual(['enabled'])
    deps.getPhoneAgentApiBase.mockReturnValue('')
    await poll.requestPhoneAgentStart('enabled')
    expect(await poll.fetchPhoneAgentStatusPayload('enabled')).toEqual({ lastPolledAt: 1000, running: false, fetchError: '当前为原版模式或未加载 Mod，无电话扩展接口' })
    expect(fetchMock).not.toHaveBeenCalled()
  })
  it.each([
    [{ success: true }, 200, null], [{ message: ' denied ' }, 400, 'denied'], [{ error: ' blocked ' }, 400, 'blocked'],
    [{}, 200, '未知错误'], [{}, 503, 'HTTP 503'], ['bad gateway', 502, 'HTTP 502 | body: bad gateway'], ['', 500, 'HTTP 500'],
  ])('reports start response %j without aborting polling', async (body, status, warning) => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    reply(body, status)
    await setup().poll.requestPhoneAgentStart('enabled')
    expect(fetchMock).toHaveBeenCalledWith('/api/mod/phone/start?channel=adb', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{"channel":"adb"}',
    })
    if (warning) expect(warn).toHaveBeenCalledWith('[奇士美 PRO] phone-agent/start:', warning)
    else expect(warn).not.toHaveBeenCalled()
  })
  it.each([
    [{ success: true, data: { running: true } }, 200, { running: true }],
    [{ message: ' failure ' }, 500, { running: false, fetchError: 'failure' }],
    [{}, 404, { running: false, fetchError: 'HTTP 404（请确认路径为 /api/mod/phone/status，勿使用 /statu 等拼写错误）' }],
    [{}, 503, { running: false, fetchError: 'HTTP 503' }], ['invalid json', 200, { running: false, fetchError: '响应缺少 data' }],
  ])('normalizes status response %j', async (body, status, expected) => {
    reply(body, status)
    expect(await setup().poll.fetchPhoneAgentStatusPayload('enabled')).toEqual({ ...expected, lastPolledAt: 1000 })
    expect(fetchMock).toHaveBeenCalledWith('/api/mod/phone/status?channel=adb')
  })
  it.each([new Error('network'), 'network'])('contains network failures %s', async (error) => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    fetchMock.mockRejectedValue(error)
    const { poll } = setup()
    await poll.requestPhoneAgentStart('enabled')
    expect(warn).toHaveBeenCalledWith('[奇士美 PRO] phone-agent/start 请求失败:', error)
    expect(await poll.fetchPhoneAgentStatusPayload('enabled')).toMatchObject({ running: false, fetchError: 'network' })
  })
  it.each([false, true])('restarts a stopped backend and stops after all employees are disabled, first running=%s', async (running) => {
    const { deps, poll } = setup()
    reply({ success: true }); reply({ success: true, data: { running } })
    if (!running) { reply({ success: true }); reply({ success: true, data: { running: true } }) }
    poll.startPhoneAgentStatusPoll()
    expect(poll.isPollActive()).toBe(true)
    await vi.advanceTimersByTimeAsync(0)
    expect(deps.onStatusUpdate).toHaveBeenCalledWith('enabled', { running: true, lastPolledAt: 1000 })
    expect(fetchMock).toHaveBeenCalledTimes(running ? 2 : 4)
    deps.readWorkflowEmployeeEnabledMap.mockReturnValue({ enabled: false, disabled: false, missing: false })
    await vi.advanceTimersByTimeAsync(2000)
    expect(poll.isPollActive()).toBe(false)
    poll.stopPhoneAgentStatusPoll()
    expect(vi.getTimerCount()).toBe(0)
  })
})
