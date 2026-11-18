import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { buildDriverScheduleFromTutorialSteps, demoGroupCleanup, waitForSelector } from './buildDriverSchedule'
import type { TutorialStep } from './types'

const mocks = vi.hoisted(() => ({ safeClick: vi.fn(), cursorClick: vi.fn(), highlightElement: vi.fn(), moveTo: vi.fn(), status: vi.fn() }))
vi.mock('./demoHelpers', () => ({
  ...mocks,
  getVirtualCursor: () => ({ moveTo: mocks.moveTo }),
  TUTORIAL_DEMO_SPEED: 1,
  sleep: (ms: number) => new Promise(resolve => setTimeout(resolve, ms)),
}))
vi.mock('@/utils/platformShellApi', () => ({ fetchEmployeePlannerStatus: mocks.status }))

beforeEach(() => { vi.useFakeTimers(); vi.clearAllMocks(); document.body.replaceChildren() })
afterEach(() => { vi.useRealTimers(); document.body.replaceChildren() })
const step = (extra: Partial<TutorialStep> = {}): TutorialStep => ({ id: 'example', title: 'Example', description: 'Demo', targetSelector: '#target', actionType: 'observe', ...extra })
function appendTarget(text = 'Target') {
  const target = document.createElement('div')
  target.id = 'target'
  target.textContent = text
  document.body.append(target)
  return target
}
function demo(input: TutorialStep) {
  const timers = { set: (callback: () => void, ms: number) => setTimeout(callback, ms), clear: vi.fn() }
  expect(buildDriverScheduleFromTutorialSteps([input])[0].demo(timers)).toEqual({ ok: true })
  return timers
}

describe('tutorial demo interactions', () => {
  it('falls back to the legacy target when its mapped click target is absent', async () => {
    const sidebar = document.createElement('aside')
    sidebar.className = 'sidebar'
    const button = document.createElement('button')
    button.dataset.view = 'chat'
    button.textContent = 'Chat'
    sidebar.append(button)
    document.body.append(sidebar)
    mocks.safeClick.mockReturnValue(false)
    demo(step({ targetSelector: '.sidebar [data-view="chat"]', actionType: 'click' }))
    await vi.advanceTimersByTimeAsync(450)
    expect(mocks.safeClick).toHaveBeenCalledWith('[data-tour="sidebar-chat"]', '点这里', 700)
    expect(mocks.cursorClick).toHaveBeenCalledWith(document.querySelector('button'), '点这里', 700)
  })

  it('observes the original target when the highlight target is absent', async () => {
    appendTarget()
    demo(step({ highlightSelector: '#missing' }))
    await vi.advanceTimersByTimeAsync(400)
    expect(mocks.moveTo).toHaveBeenCalledWith(document.querySelector('#target'), { duration: 650, label: '看这里' })
    expect(mocks.highlightElement).toHaveBeenCalledWith(document.querySelector('#target'))
  })

  it('does nothing when neither observation target exists and clears timer groups', async () => {
    const timers = demo(step())
    await vi.advanceTimersByTimeAsync(400)
    expect(mocks.moveTo).not.toHaveBeenCalled()
    demoGroupCleanup(timers)
    expect(timers.clear).toHaveBeenCalledOnce()
    demoGroupCleanup(null)
  })

  it('retries employee readiness after a transient failure until tools are registered', async () => {
    appendTarget('Installing')
    mocks.status.mockRejectedValueOnce(new Error('temporarily unavailable')).mockResolvedValueOnce({ office_ready: true, registered_tool_count: 0 }).mockResolvedValueOnce({ office_ready: true, registered_tool_count: 1 })
    demo(step({ id: 'office-pack-wait-ready' }))
    await vi.advanceTimersByTimeAsync(400)
    // Let the lazy module import settle before moving the polling clock.
    await vi.waitFor(() => expect(mocks.status).toHaveBeenCalledTimes(1))
    await vi.advanceTimersByTimeAsync(3000)
    expect(mocks.status).toHaveBeenCalledTimes(3)
    expect(mocks.status).toHaveBeenLastCalledWith(true)
    expect(mocks.moveTo).toHaveBeenCalledWith(document.querySelector('#target'), { duration: 650, label: '安装中…' })
    await vi.advanceTimersByTimeAsync(3000)
    expect(mocks.status).toHaveBeenCalledTimes(3)
  })
})

describe('waitForSelector visibility', () => {
  it('waits for nonzero layout dimensions, not just DOM presence', async () => {
    const target = appendTarget('')
    const size = vi.spyOn(target, 'getBoundingClientRect').mockReturnValue({ width: 0, height: 0 } as DOMRect)
    const pending = waitForSelector('#target', 500, 100)
    await vi.advanceTimersByTimeAsync(100)
    size.mockReturnValue({ width: 40, height: 20 } as DOMRect)
    await vi.advanceTimersByTimeAsync(100)
    await expect(pending).resolves.toBe(target)
  })

  it('returns null for an empty selector or a target that never appears', async () => {
    await expect(waitForSelector(' ')).resolves.toBeNull()
    const pending = waitForSelector('#missing', 200, 100)
    await vi.advanceTimersByTimeAsync(200)
    await expect(pending).resolves.toBeNull()
  })
})
