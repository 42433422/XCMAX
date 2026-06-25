import { describe, expect, it, beforeEach, vi, afterEach } from 'vitest'
import { QUICK_START_PAGE_HIGHLIGHTS } from './quickStartPageHighlights'
import {
  QUICK_START_FOCUS_NAV_KEYS,
  QUICK_START_PAGE_ROUTE,
  QUICK_START_NAV_INTRO,
} from './quickStartNav'
import { buildAssistantFloatSteps } from './buildAssistantFloatTour'
import { closeAssistantFloatPanelForTutorial, isAssistantFloatPanelOpen } from './assistantFloatTutorial'
import { isOnboardingDriverTutorialActive } from './onboardingTutorialActive'
import {
  TUTORIAL_DEMO_SPEED,
  makeTimerGroup,
  getVirtualCursor,
  cursorClick,
  safeClick,
  fireKey,
  highlightElement,
  sleep,
} from './demoHelpers'
import {
  buildDriverScheduleFromTutorialSteps,
  waitForSelector,
  demoGroupCleanup,
} from './buildDriverSchedule'
import { filterStepsForPro, resolveTrackSteps, resolveAllWarmupSteps } from './resolveSteps'
import {
  fetchTutorialSampleFile,
  assignFileToInput,
  injectExcelAnalyzeSample,
  uploadOfficeSampleForPath,
  readWordSampleViaOfficePack,
  runQuickStartExcelDemo,
  runQuickStartWordDemo,
  waitForChatContains,
  cleanupQuickStartImportDemo,
} from './tutorialOfficeImportDemo'
import {
  clearTutorialDbSampleIds,
  seedQuickStartTutorialDbSamples,
  purgeQuickStartTutorialDbSamples,
  runQuickStartDeleteCustomersDemo,
  runQuickStartDeleteProductsDemo,
} from './tutorialDbSampleDemo'
import {
  launchAdvancedDriverTour,
  promptAdvancedTutorialAfterInstall,
  resolveRouteNameFromPath,
} from './promptAdvancedTutorial'
import type { TutorialStep } from './types'

// jsdom 没有 DataTransfer，需要 mock
// input.files setter 需要 FileList 类型，所以用 Object.defineProperty 绕过
class MockDataTransfer {
  files: File[] = []
  items = {
    add: (file: File) => {
      this.files.push(file)
    },
  }
}
;(globalThis as unknown as { DataTransfer: unknown }).DataTransfer = MockDataTransfer

/** 在 input 元素上覆盖 files setter，绕过 jsdom 的 FileList 类型检查 */
function patchInputFilesSetter(input: HTMLInputElement): void {
  Object.defineProperty(input, 'files', {
    configurable: true,
    get() {
      return (this as unknown as { _mockFiles?: File[] })._mockFiles || null
    },
    set(value: File[]) {
      ;(this as unknown as { _mockFiles?: File[] })._mockFiles = value
    },
  })
}

vi.mock('@/api/customers', () => ({
  customersApi: {
    createCustomer: vi.fn(),
    batchDeleteCustomers: vi.fn(),
  },
}))

vi.mock('@/api/products', () => ({
  productsApi: {
    createProduct: vi.fn(),
    batchDeleteProducts: vi.fn(),
  },
}))

vi.mock('@/utils/officeEmployeeReadApi', () => ({
  uploadTutorialOfficeFile: vi.fn(),
  readWordViaOfficePack: vi.fn(),
}))

vi.mock('@/utils/platformShellApi', () => ({
  fetchEmployeePlannerStatus: vi.fn(),
}))

vi.mock('@/utils/appDialog', () => ({
  appConfirm: vi.fn(),
}))

const officeApiMock = await import('@/utils/officeEmployeeReadApi')
const customersApiMock = (await import('@/api/customers')).customersApi
const productsApiMock = (await import('@/api/products')).productsApi
const appConfirmMock = (await import('@/utils/appDialog')).appConfirm

describe('quickStartPageHighlights', () => {
  it('exports highlights for chat, workflow-employee-space, im, and settings', () => {
    expect(Object.keys(QUICK_START_PAGE_HIGHLIGHTS).sort()).toEqual(
      ['chat', 'im', 'settings', 'workflow-employee-space'].sort(),
    )
  })

  it('chat highlights have three entries with targetSelector', () => {
    const chatHighlights = QUICK_START_PAGE_HIGHLIGHTS.chat
    expect(chatHighlights).toHaveLength(3)
    for (const h of chatHighlights) {
      expect(typeof h.idSuffix).toBe('string')
      expect(typeof h.title).toBe('string')
      expect(typeof h.description).toBe('string')
      expect(typeof h.targetSelector).toBe('string')
    }
  })

  it('workflow-employee-space highlights have head and desks entries', () => {
    const highlights = QUICK_START_PAGE_HIGHLIGHTS['workflow-employee-space']
    expect(highlights).toHaveLength(2)
    expect(highlights[0].idSuffix).toBe('head')
    expect(highlights[1].idSuffix).toBe('desks')
  })

  it('settings highlights include model-payment and recharge entries', () => {
    const highlights = QUICK_START_PAGE_HIGHLIGHTS.settings
    expect(highlights.length).toBeGreaterThanOrEqual(3)
    const suffixes = highlights.map((h) => h.idSuffix)
    expect(suffixes).toContain('model-payment')
    expect(suffixes).toContain('recharge')
  })

  it('im highlights have sidebar, thread, compose entries', () => {
    const highlights = QUICK_START_PAGE_HIGHLIGHTS.im
    expect(highlights).toHaveLength(3)
    const suffixes = highlights.map((h) => h.idSuffix)
    expect(suffixes).toEqual(['sidebar', 'thread', 'compose'])
  })
})

describe('quickStartNav', () => {
  it('QUICK_START_FOCUS_NAV_KEYS has five entries in order', () => {
    expect(QUICK_START_FOCUS_NAV_KEYS).toEqual([
      'chat',
      'ai-ecosystem',
      'employee-workflow',
      'im',
      'settings',
    ])
  })

  it('QUICK_START_PAGE_ROUTE maps employee-workflow to workflow-employee-space', () => {
    expect(QUICK_START_PAGE_ROUTE['employee-workflow']).toBe('workflow-employee-space')
  })

  it('QUICK_START_PAGE_ROUTE only has employee-workflow mapping', () => {
    expect(Object.keys(QUICK_START_PAGE_ROUTE)).toEqual(['employee-workflow'])
  })

  it('QUICK_START_NAV_INTRO has intro text for all five nav keys', () => {
    for (const key of QUICK_START_FOCUS_NAV_KEYS) {
      expect(QUICK_START_NAV_INTRO[key]).toBeTruthy()
      expect(typeof QUICK_START_NAV_INTRO[key]).toBe('string')
      expect(QUICK_START_NAV_INTRO[key]!.length).toBeGreaterThan(0)
    }
  })
})

describe('buildAssistantFloatTour', () => {
  it('buildAssistantFloatSteps returns three steps', () => {
    const steps = buildAssistantFloatSteps()
    expect(steps).toHaveLength(3)
  })

  it('first step is the assistant toggle (click)', () => {
    const steps = buildAssistantFloatSteps()
    expect(steps[0].id).toBe('page-chat-assistant-toggle')
    expect(steps[0].actionType).toBe('click')
    expect(steps[0].routeName).toBe('chat')
    expect(steps[0].targetSelector).toContain('assistant-float-toggle')
  })

  it('second step is the panel overview (observe)', () => {
    const steps = buildAssistantFloatSteps()
    expect(steps[1].id).toBe('page-chat-assistant-panel')
    expect(steps[1].actionType).toBe('observe')
    expect(steps[1].noAutoSkipWhenMissing).toBe(true)
  })

  it('third step is closing the panel (click)', () => {
    const steps = buildAssistantFloatSteps()
    expect(steps[2].id).toBe('page-chat-assistant-close')
    expect(steps[2].actionType).toBe('click')
  })

  it('all steps target chat route', () => {
    const steps = buildAssistantFloatSteps()
    for (const s of steps) {
      expect(s.routeName).toBe('chat')
      expect(s.allowCardNext).toBe(true)
      expect(s.excludeInPro).toBe(false)
    }
  })
})

describe('assistantFloatTutorial', () => {
  afterEach(() => {
    document.body.innerHTML = ''
  })

  it('isAssistantFloatPanelOpen returns false when panel not present', () => {
    expect(isAssistantFloatPanelOpen()).toBe(false)
  })

  it('isAssistantFloatPanelOpen returns true when panel present', () => {
    const panel = document.createElement('div')
    panel.setAttribute('data-tutorial-spotlight', 'assistant-panel')
    document.body.appendChild(panel)
    expect(isAssistantFloatPanelOpen()).toBe(true)
  })

  it('closeAssistantFloatPanelForTutorial does nothing when panel absent', () => {
    expect(() => closeAssistantFloatPanelForTutorial()).not.toThrow()
  })

  it('closeAssistantFloatPanelForTutorial clicks close button when present', () => {
    const panel = document.createElement('div')
    panel.setAttribute('data-tutorial-spotlight', 'assistant-panel')
    document.body.appendChild(panel)

    const closeBtn = document.createElement('button')
    closeBtn.setAttribute('data-tour', 'assistant-float-close')
    const clickSpy = vi.fn()
    closeBtn.addEventListener('click', clickSpy)
    document.body.appendChild(closeBtn)

    closeAssistantFloatPanelForTutorial()
    expect(clickSpy).toHaveBeenCalled()
  })

  it('closeAssistantFloatPanelForTutorial clicks assistant-close when data-tour close absent', () => {
    const panel = document.createElement('div')
    panel.setAttribute('data-tutorial-spotlight', 'assistant-panel')
    panel.className = 'assistant-float-panel'
    document.body.appendChild(panel)

    const closeBtn = document.createElement('button')
    closeBtn.className = 'assistant-close'
    const clickSpy = vi.fn()
    closeBtn.addEventListener('click', clickSpy)
    panel.appendChild(closeBtn)

    closeAssistantFloatPanelForTutorial()
    expect(clickSpy).toHaveBeenCalled()
  })

  it('closeAssistantFloatPanelForTutorial toggles when only toggle button present and expanded', () => {
    const panel = document.createElement('div')
    panel.setAttribute('data-tutorial-spotlight', 'assistant-panel')
    document.body.appendChild(panel)

    const toggle = document.createElement('button')
    toggle.setAttribute('data-tour', 'assistant-float-toggle')
    toggle.setAttribute('aria-expanded', 'true')
    const clickSpy = vi.fn()
    toggle.addEventListener('click', clickSpy)
    document.body.appendChild(toggle)

    closeAssistantFloatPanelForTutorial()
    expect(clickSpy).toHaveBeenCalled()
  })

  it('closeAssistantFloatPanelForTutorial does not toggle when toggle not expanded', () => {
    const panel = document.createElement('div')
    panel.setAttribute('data-tutorial-spotlight', 'assistant-panel')
    document.body.appendChild(panel)

    const toggle = document.createElement('button')
    toggle.setAttribute('data-tour', 'assistant-float-toggle')
    toggle.setAttribute('aria-expanded', 'false')
    const clickSpy = vi.fn()
    toggle.addEventListener('click', clickSpy)
    document.body.appendChild(toggle)

    closeAssistantFloatPanelForTutorial()
    expect(clickSpy).not.toHaveBeenCalled()
  })
})

describe('onboardingTutorialActive', () => {
  afterEach(() => {
    document.body.classList.remove('tutorial-active')
  })

  it('returns false when store inactive and body lacks class', () => {
    expect(isOnboardingDriverTutorialActive()).toBe(false)
  })

  it('returns true when body has tutorial-active class', () => {
    document.body.classList.add('tutorial-active')
    expect(isOnboardingDriverTutorialActive()).toBe(true)
  })
})

describe('demoHelpers', () => {
  it('TUTORIAL_DEMO_SPEED is 2.0', () => {
    expect(TUTORIAL_DEMO_SPEED).toBe(2.0)
  })

  describe('makeTimerGroup', () => {
    beforeEach(() => {
      vi.useFakeTimers()
    })
    afterEach(() => {
      vi.useRealTimers()
    })

    it('set schedules a timeout and clear cancels pending timers', () => {
      const timers = makeTimerGroup()
      let hit = 0
      timers.set(() => {
        hit += 1
      }, 500)
      timers.clear()
      vi.advanceTimersByTime(600)
      expect(hit).toBe(0)
    })

    it('set fires callback after delay', () => {
      const timers = makeTimerGroup()
      let hit = 0
      timers.set(() => {
        hit += 1
      }, 100)
      vi.advanceTimersByTime(100)
      expect(hit).toBe(1)
    })

    it('clear is idempotent', () => {
      const timers = makeTimerGroup()
      expect(() => {
        timers.clear()
        timers.clear()
      }).not.toThrow()
    })
  })

  describe('getVirtualCursor', () => {
    it('returns undefined when window.virtualCursor not set', () => {
      delete (window as unknown as { virtualCursor?: unknown }).virtualCursor
      expect(getVirtualCursor()).toBeUndefined()
    })

    it('returns the cursor when set', () => {
      const fake = {
        moveTo: vi.fn(),
        click: vi.fn(),
        hide: vi.fn(),
        show: vi.fn(),
      }
      ;(window as unknown as { virtualCursor?: unknown }).virtualCursor = fake
      expect(getVirtualCursor()).toBe(fake)
      delete (window as unknown as { virtualCursor?: unknown }).virtualCursor
    })
  })

  describe('cursorClick', () => {
    beforeEach(() => {
      vi.useFakeTimers()
    })
    afterEach(() => {
      vi.useRealTimers()
    })

    it('clicks the element after duration via virtualCursor when available', () => {
      const el = document.createElement('button')
      const clickSpy = vi.fn()
      el.addEventListener('click', clickSpy)
      const vc = {
        moveTo: vi.fn(),
        click: vi.fn(),
        hide: vi.fn(),
        show: vi.fn(),
      }
      ;(window as unknown as { virtualCursor?: unknown }).virtualCursor = vc

      cursorClick(el, '点这里', 100)
      expect(vc.click).toHaveBeenCalledWith(el, { duration: 100, label: '点这里' })
      vi.advanceTimersByTime(100)
      expect(clickSpy).toHaveBeenCalled()

      delete (window as unknown as { virtualCursor?: unknown }).virtualCursor
    })

    it('clicks the element after duration even without virtualCursor', () => {
      const el = document.createElement('button')
      const clickSpy = vi.fn()
      el.addEventListener('click', clickSpy)
      delete (window as unknown as { virtualCursor?: unknown }).virtualCursor

      cursorClick(el, undefined, 50)
      vi.advanceTimersByTime(50)
      expect(clickSpy).toHaveBeenCalled()
    })
  })

  describe('safeClick', () => {
    beforeEach(() => {
      vi.useFakeTimers()
    })
    afterEach(() => {
      vi.useRealTimers()
    })

    it('returns false when selector not found', () => {
      expect(safeClick('.not-found')).toBe(false)
    })

    it('returns true and clicks when element found', () => {
      const el = document.createElement('button')
      el.className = 'target'
      document.body.appendChild(el)
      const clickSpy = vi.fn()
      el.addEventListener('click', clickSpy)

      const result = safeClick('.target', 'label', 50)
      expect(result).toBe(true)
      vi.advanceTimersByTime(50)
      expect(clickSpy).toHaveBeenCalled()

      el.remove()
    })
  })

  describe('fireKey', () => {
    it('dispatches a keydown event on document', () => {
      const spy = vi.fn()
      document.addEventListener('keydown', spy)
      fireKey('Enter', 'Enter')
      expect(spy).toHaveBeenCalled()
      const ev = spy.mock.calls[0][0] as KeyboardEvent
      expect(ev.key).toBe('Enter')
      document.removeEventListener('keydown', spy)
    })
  })

  describe('highlightElement', () => {
    beforeEach(() => {
      vi.useFakeTimers()
    })
    afterEach(() => {
      vi.useRealTimers()
    })

    it('applies outline style and clears after timeout', () => {
      const el = document.createElement('div')
      highlightElement(el, 200)
      expect(el.style.outline).toContain('2px solid #3b82f6')
      vi.advanceTimersByTime(200)
      expect(el.style.outline).toBe('')
    })
  })

  describe('sleep', () => {
    beforeEach(() => {
      vi.useFakeTimers()
    })
    afterEach(() => {
      vi.useRealTimers()
    })

    it('resolves after the given ms', async () => {
      let resolved = false
      const p = sleep(100).then(() => {
        resolved = true
      })
      vi.advanceTimersByTime(100)
      await p
      expect(resolved).toBe(true)
    })
  })
})

describe('buildDriverSchedule (additional coverage)', () => {
  it('filters out steps without id', () => {
    const steps = [
      { id: '', title: 'empty', description: 'd', targetSelector: '.a', actionType: 'click' },
      { id: 'real', title: 'real', description: 'd', targetSelector: '.b', actionType: 'observe' },
    ] as TutorialStep[]
    const schedule = buildDriverScheduleFromTutorialSteps(steps)
    expect(schedule).toHaveLength(1)
    expect(schedule[0].id).toBe('real')
  })

  it('returns empty array for empty input', () => {
    expect(buildDriverScheduleFromTutorialSteps([])).toEqual([])
  })

  it('office-pack-wait-ready step uses observe demo with timers', () => {
    vi.useFakeTimers()
    const steps: TutorialStep[] = [
      {
        id: 'office-pack-wait-ready',
        title: 'wait',
        description: 'd',
        targetSelector: '[data-tour="store-shell"]',
        actionType: 'observe',
      },
    ]
    const schedule = buildDriverScheduleFromTutorialSteps(steps)
    expect(schedule[0].actionType).toBe('observe')
    const timers = makeTimerGroup()
    const result = schedule[0].demo(timers)
    expect(result.ok).toBe(true)
    timers.clear()
    vi.useRealTimers()
  })

  it('click step uses safeClick demo', () => {
    vi.useFakeTimers()
    const steps: TutorialStep[] = [
      {
        id: 'click-step',
        title: 'click',
        description: 'd',
        targetSelector: '[data-tour="sidebar-menu"]',
        actionType: 'click',
      },
    ]
    const schedule = buildDriverScheduleFromTutorialSteps(steps)
    const timers = makeTimerGroup()
    const result = schedule[0].demo(timers)
    expect(result.ok).toBe(true)
    timers.clear()
    vi.useRealTimers()
  })

  it('observe step uses highlight demo', () => {
    vi.useFakeTimers()
    const el = document.createElement('div')
    el.style.width = '100px'
    el.style.height = '100px'
    document.body.appendChild(el)
    const steps: TutorialStep[] = [
      {
        id: 'observe-step',
        title: 'observe',
        description: 'd',
        targetSelector: 'div',
        actionType: 'observe',
      },
    ]
    const schedule = buildDriverScheduleFromTutorialSteps(steps)
    const timers = makeTimerGroup()
    const result = schedule[0].demo(timers)
    expect(result.ok).toBe(true)
    timers.clear()
    el.remove()
    vi.useRealTimers()
  })

  describe('waitForSelector', () => {
    it('returns null for empty selector', async () => {
      const result = await waitForSelector('', 50)
      expect(result).toBeNull()
    })

    it('returns null when selector not found within maxMs', async () => {
      vi.useFakeTimers()
      const promise = waitForSelector('.not-found', 100, 50)
      vi.advanceTimersByTime(150)
      const result = await promise
      expect(result).toBeNull()
      vi.useRealTimers()
    })

    it('returns element when found and visible', async () => {
      const el = document.createElement('div')
      el.className = 'found'
      el.getBoundingClientRect = () => ({ width: 100, height: 100, top: 0, left: 0, right: 100, bottom: 100, x: 0, y: 0, toJSON: () => {} } as DOMRect)
      document.body.appendChild(el)
      const result = await waitForSelector('.found', 1000, 50)
      expect(result).toBe(el)
      el.remove()
    })

    it('returns null when element found but not visible', async () => {
      vi.useFakeTimers()
      const el = document.createElement('div')
      el.className = 'invisible'
      el.style.width = '0px'
      el.style.height = '0px'
      document.body.appendChild(el)
      const promise = waitForSelector('.invisible', 100, 50)
      vi.advanceTimersByTime(150)
      const result = await promise
      expect(result).toBeNull()
      el.remove()
      vi.useRealTimers()
    })
  })

  it('demoGroupCleanup clears timers', () => {
    vi.useFakeTimers()
    const timers = makeTimerGroup()
    let hit = 0
    timers.set(() => {
      hit += 1
    }, 500)
    demoGroupCleanup(timers)
    vi.advanceTimersByTime(600)
    expect(hit).toBe(0)
    vi.useRealTimers()
  })

  it('demoGroupCleanup handles null', () => {
    expect(() => demoGroupCleanup(null)).not.toThrow()
  })
})

describe('resolveSteps', () => {
  const baseCtx = {
    industryId: 'default',
    mods: [],
    visibleNav: [],
    isProMode: false,
    modMenuKeys: new Set<string>(),
  }

  describe('filterStepsForPro', () => {
    it('keeps all steps when not pro', () => {
      const steps = [
        { id: 'a', excludeInPro: true } as TutorialStep,
        { id: 'b', excludeInPro: false } as TutorialStep,
      ]
      expect(filterStepsForPro(steps, false)).toHaveLength(2)
    })

    it('filters out excludeInPro steps when pro', () => {
      const steps = [
        { id: 'a', excludeInPro: true } as TutorialStep,
        { id: 'b', excludeInPro: false } as TutorialStep,
      ]
      const result = filterStepsForPro(steps, true)
      expect(result).toHaveLength(1)
      expect(result[0].id).toBe('b')
    })

    it('keeps steps without excludeInPro flag in pro mode', () => {
      const steps = [{ id: 'a' } as TutorialStep]
      expect(filterStepsForPro(steps, true)).toHaveLength(1)
    })
  })

  describe('resolveTrackSteps', () => {
    it('returns basic steps for basic track', () => {
      const steps = resolveTrackSteps('basic', baseCtx)
      expect(steps.length).toBeGreaterThan(0)
      expect(steps[0].id).toBeTruthy()
    })

    it('returns advanced steps for advanced track', () => {
      const steps = resolveTrackSteps('advanced', baseCtx)
      expect(steps.length).toBeGreaterThan(0)
    })

    it('falls back to advanced when unknown track has no mod steps', () => {
      const steps = resolveTrackSteps('unknown-track', baseCtx)
      expect(steps.length).toBeGreaterThan(0)
    })

    it('treats empty track id as basic', () => {
      const steps = resolveTrackSteps('', baseCtx)
      expect(steps.length).toBeGreaterThan(0)
    })

    it('treats whitespace-only track id as basic', () => {
      const steps = resolveTrackSteps('   ', baseCtx)
      expect(steps.length).toBeGreaterThan(0)
    })

    it('filters pro steps when isProMode is true', () => {
      const proCtx = { ...baseCtx, isProMode: true }
      const steps = resolveTrackSteps('basic', proCtx)
      for (const s of steps) {
        expect(s.excludeInPro).toBeFalsy()
      }
    })
  })

  describe('resolveAllWarmupSteps', () => {
    it('combines basic and advanced steps with dedup', () => {
      const all = resolveAllWarmupSteps(baseCtx)
      expect(all.length).toBeGreaterThan(0)
      const ids = all.map((s) => s.id)
      const unique = new Set(ids)
      expect(unique.size).toBe(ids.length)
    })
  })
})

describe('tutorialOfficeImportDemo', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(officeApiMock.uploadTutorialOfficeFile).mockReset()
    vi.mocked(officeApiMock.readWordViaOfficePack).mockReset()
    document.body.innerHTML = ''
  })

  describe('fetchTutorialSampleFile', () => {
    it('throws when fetch fails', async () => {
      const okSpy = vi.fn().mockReturnValue(false)
      const blobSpy = vi.fn()
      const fetchSpy = vi.fn().mockResolvedValue({ ok: false, status: 404, blob: blobSpy } as unknown as Response)
      vi.stubGlobal('fetch', fetchSpy)
      Object.defineProperty(globalThis, 'fetch', { value: fetchSpy, configurable: true, writable: true })
      await expect(fetchTutorialSampleFile('/url', 'f.xlsx')).rejects.toThrow('样本下载失败 HTTP 404')
    })

    it('returns a File when fetch succeeds', async () => {
      const blob = new Blob(['data'], { type: 'application/octet-stream' })
      const fetchSpy = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        blob: () => Promise.resolve(blob),
      } as unknown as Response)
      vi.stubGlobal('fetch', fetchSpy)
      Object.defineProperty(globalThis, 'fetch', { value: fetchSpy, configurable: true, writable: true })
      const file = await fetchTutorialSampleFile('/url', 'f.xlsx')
      expect(file).toBeInstanceOf(File)
      expect(file.name).toBe('f.xlsx')
    })
  })

  describe('assignFileToInput', () => {
    it('assigns file to input and dispatches change event', () => {
      const input = document.createElement('input')
      input.type = 'file'
      patchInputFilesSetter(input)
      const changeSpy = vi.fn()
      input.addEventListener('change', changeSpy)
      const file = new File(['data'], 'test.xlsx')
      assignFileToInput(input, file)
      expect(input.files).not.toBeNull()
      expect(input.files!.length).toBe(1)
      expect(input.files![0].name).toBe('test.xlsx')
      expect(changeSpy).toHaveBeenCalled()
    })
  })

  describe('injectExcelAnalyzeSample', () => {
    it('throws when chat file input not found', async () => {
      await expect(injectExcelAnalyzeSample('/url', 'f.xlsx')).rejects.toThrow('未找到对话页上传控件')
    })

    it('assigns file when input found and fetch succeeds', async () => {
      const input = document.createElement('input')
      input.type = 'file'
      patchInputFilesSetter(input)
      const wrapper = document.createElement('div')
      wrapper.id = 'view-chat'
      wrapper.appendChild(input)
      document.body.appendChild(wrapper)

      const blob = new Blob(['data'], { type: 'application/octet-stream' })
      const fetchSpy = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        blob: () => Promise.resolve(blob),
      } as unknown as Response)
      vi.stubGlobal('fetch', fetchSpy)
      Object.defineProperty(globalThis, 'fetch', { value: fetchSpy, configurable: true, writable: true })

      await injectExcelAnalyzeSample('/url', 'f.xlsx')
      expect(input.files).not.toBeNull()
      expect(input.files!.length).toBe(1)
    })
  })

  describe('uploadOfficeSampleForPath', () => {
    it('tracks and returns uploaded file_path', async () => {
      sessionStorage.clear()
      vi.mocked(officeApiMock.uploadTutorialOfficeFile).mockResolvedValue({
        file_path: '/uploaded/path.xlsx',
        workspace_root: '/root',
        filename: 'path.xlsx',
      })
      const file = new File(['d'], 'f.xlsx')
      const result = await uploadOfficeSampleForPath(file)
      expect(result).toBe('/uploaded/path.xlsx')
      expect(officeApiMock.uploadTutorialOfficeFile).toHaveBeenCalledWith(file)
    })
  })

  describe('readWordSampleViaOfficePack', () => {
    it('uploads and reads word file', async () => {
      sessionStorage.clear()
      vi.mocked(officeApiMock.uploadTutorialOfficeFile).mockResolvedValue({
        file_path: '/p.docx',
        workspace_root: '/root',
        filename: 'p.docx',
      })
      vi.mocked(officeApiMock.readWordViaOfficePack).mockResolvedValue({ ok: true, summary: 'done' })
      const file = new File(['d'], 'f.docx')
      const result = await readWordSampleViaOfficePack(file)
      expect(result.ok).toBe(true)
      expect(result.summary).toBe('done')
    })
  })

  describe('runQuickStartExcelDemo', () => {
    it('injects sample a when which=a', async () => {
      const input = document.createElement('input')
      input.type = 'file'
      patchInputFilesSetter(input)
      const wrapper = document.createElement('div')
      wrapper.id = 'view-chat'
      wrapper.appendChild(input)
      document.body.appendChild(wrapper)

      const blob = new Blob(['data'], { type: 'application/octet-stream' })
      const fetchSpy = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        blob: () => Promise.resolve(blob),
      } as unknown as Response)
      vi.stubGlobal('fetch', fetchSpy)
      Object.defineProperty(globalThis, 'fetch', { value: fetchSpy, configurable: true, writable: true })

      await runQuickStartExcelDemo('a')
      expect(input.files!.length).toBe(1)
      expect(input.files![0].name).toBe('xcagi-quickstart-sample-a.xlsx')
      expect(fetchSpy).toHaveBeenCalledWith('/tutorial/xcagi-quickstart-sample-a.xlsx', {
        credentials: 'same-origin',
      })
    })

    it('injects sample b when which=b', async () => {
      const input = document.createElement('input')
      input.type = 'file'
      patchInputFilesSetter(input)
      const wrapper = document.createElement('div')
      wrapper.id = 'view-chat'
      wrapper.appendChild(input)
      document.body.appendChild(wrapper)

      const blob = new Blob(['data'], { type: 'application/octet-stream' })
      const fetchSpy = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        blob: () => Promise.resolve(blob),
      } as unknown as Response)
      vi.stubGlobal('fetch', fetchSpy)
      Object.defineProperty(globalThis, 'fetch', { value: fetchSpy, configurable: true, writable: true })

      await runQuickStartExcelDemo('b')
      expect(input.files![0].name).toBe('xcagi-quickstart-sample-b.xlsx')
    })
  })

  describe('runQuickStartWordDemo', () => {
    it('dispatches ai chat line event when word read succeeds', async () => {
      const blob = new Blob(['data'], { type: 'application/octet-stream' })
      const fetchSpy = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        blob: () => Promise.resolve(blob),
      } as unknown as Response)
      vi.stubGlobal('fetch', fetchSpy)
      Object.defineProperty(globalThis, 'fetch', { value: fetchSpy, configurable: true, writable: true })

      vi.mocked(officeApiMock.uploadTutorialOfficeFile).mockResolvedValue({
        file_path: '/p.docx',
        workspace_root: '/root',
        filename: 'p.docx',
      })
      vi.mocked(officeApiMock.readWordViaOfficePack).mockResolvedValue({ ok: true, summary: 'Word ok' })

      const dispatchSpy = vi.spyOn(window, 'dispatchEvent')
      await runQuickStartWordDemo()
      const customEvents = dispatchSpy.mock.calls
        .map((c) => c[0])
        .filter((e): e is CustomEvent => e instanceof CustomEvent)
      expect(customEvents.length).toBeGreaterThan(0)
      const event = customEvents[customEvents.length - 1]
      expect(event.type).toBe('xcagi:tutorial-chat-line')
      expect((event.detail as { role: string }).role).toBe('ai')
      dispatchSpy.mockRestore()
    })

    it('dispatches task chat line event when word read fails', async () => {
      const blob = new Blob(['data'], { type: 'application/octet-stream' })
      const fetchSpy = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        blob: () => Promise.resolve(blob),
      } as unknown as Response)
      vi.stubGlobal('fetch', fetchSpy)
      Object.defineProperty(globalThis, 'fetch', { value: fetchSpy, configurable: true, writable: true })

      vi.mocked(officeApiMock.uploadTutorialOfficeFile).mockResolvedValue({
        file_path: '/p.docx',
        workspace_root: '/root',
        filename: 'p.docx',
      })
      vi.mocked(officeApiMock.readWordViaOfficePack).mockResolvedValue({ ok: false, summary: 'failed' })

      const dispatchSpy = vi.spyOn(window, 'dispatchEvent')
      await runQuickStartWordDemo()
      const customEvents = dispatchSpy.mock.calls
        .map((c) => c[0])
        .filter((e): e is CustomEvent => e instanceof CustomEvent)
      const event = customEvents[customEvents.length - 1]
      expect((event.detail as { role: string }).role).toBe('task')
      dispatchSpy.mockRestore()
    })
  })

  describe('waitForChatContains', () => {
    it('returns true immediately for empty text', async () => {
      expect(await waitForChatContains('')).toBe(true)
      expect(await waitForChatContains('   ')).toBe(true)
    })

    it('returns true when text already present in chat container', async () => {
      const parent = document.createElement('div')
      parent.id = 'view-chat'
      const container = document.createElement('div')
      container.className = 'chat-container'
      container.textContent = 'hello world'
      parent.appendChild(container)
      document.body.appendChild(parent)
      expect(await waitForChatContains('hello', 1000)).toBe(true)
      parent.remove()
    })

    it('returns false when text not present within maxMs', async () => {
      vi.useFakeTimers()
      const parent = document.createElement('div')
      parent.id = 'view-chat'
      const container = document.createElement('div')
      container.className = 'chat-container'
      container.textContent = 'nothing here'
      parent.appendChild(container)
      document.body.appendChild(parent)
      const promise = waitForChatContains('target', 100, 50)
      // sleep(400) 需要至少 400ms 才能解析；推进 500ms 让循环退出
      await vi.advanceTimersByTimeAsync(500)
      const result = await promise
      expect(result).toBe(false)
      parent.remove()
      vi.useRealTimers()
    })
  })

  describe('cleanupQuickStartImportDemo', () => {
    it('clears stored paths and clicks new conversation button when present', async () => {
      sessionStorage.clear()
      sessionStorage.setItem('xcagi_tutorial_office_upload_paths', JSON.stringify(['/a.xlsx']))

      const btn = document.createElement('button')
      btn.id = 'newConversationBtn'
      const clickSpy = vi.fn()
      btn.addEventListener('click', clickSpy)
      document.body.appendChild(btn)

      const fetchSpy = vi.fn().mockResolvedValue({ ok: true } as unknown as Response)
      vi.stubGlobal('fetch', fetchSpy)
      Object.defineProperty(globalThis, 'fetch', { value: fetchSpy, configurable: true, writable: true })

      await cleanupQuickStartImportDemo()
      expect(clickSpy).toHaveBeenCalled()
      expect(sessionStorage.getItem('xcagi_tutorial_office_upload_paths')).toBeNull()
    })

    it('does not call fetch when no paths stored', async () => {
      sessionStorage.clear()
      const fetchSpy = vi.fn()
      vi.stubGlobal('fetch', fetchSpy)
      Object.defineProperty(globalThis, 'fetch', { value: fetchSpy, configurable: true, writable: true })
      await cleanupQuickStartImportDemo()
      expect(fetchSpy).not.toHaveBeenCalled()
    })
  })
})

describe('tutorialDbSampleDemo', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(customersApiMock.createCustomer).mockReset()
    vi.mocked(customersApiMock.batchDeleteCustomers).mockReset()
    vi.mocked(productsApiMock.createProduct).mockReset()
    vi.mocked(productsApiMock.batchDeleteProducts).mockReset()
    sessionStorage.clear()
    document.body.innerHTML = ''
  })

  describe('clearTutorialDbSampleIds', () => {
    it('removes stored ids from sessionStorage', () => {
      sessionStorage.setItem('xcagi_tutorial_db_sample_ids', JSON.stringify({ customerIds: [1], productIds: [2] }))
      clearTutorialDbSampleIds()
      expect(sessionStorage.getItem('xcagi_tutorial_db_sample_ids')).toBeNull()
    })

    it('does not throw when nothing stored', () => {
      expect(() => clearTutorialDbSampleIds()).not.toThrow()
    })
  })

  describe('seedQuickStartTutorialDbSamples', () => {
    it('creates two customers and four products and stores ids', async () => {
      vi.mocked(customersApiMock.createCustomer)
        .mockResolvedValueOnce({ data: { id: 101 } } as never)
        .mockResolvedValueOnce({ data: { id: 102 } } as never)
      vi.mocked(productsApiMock.createProduct)
        .mockResolvedValueOnce({ data: { id: 201 } } as never)
        .mockResolvedValueOnce({ data: { id: 202 } } as never)
        .mockResolvedValueOnce({ data: { id: 203 } } as never)
        .mockResolvedValueOnce({ data: { id: 204 } } as never)

      const ids = await seedQuickStartTutorialDbSamples()
      expect(ids.customerIds).toEqual([101, 102])
      expect(ids.productIds).toEqual([201, 202, 203, 204])
      expect(customersApiMock.createCustomer).toHaveBeenCalledTimes(2)
      expect(productsApiMock.createProduct).toHaveBeenCalledTimes(4)

      const stored = JSON.parse(sessionStorage.getItem('xcagi_tutorial_db_sample_ids') || '{}')
      expect(stored.customerIds).toEqual([101, 102])
      expect(stored.productIds).toEqual([201, 202, 203, 204])
    })

    it('skips ids when createCustomer throws', async () => {
      vi.mocked(customersApiMock.createCustomer).mockRejectedValue(new Error('exists'))
      vi.mocked(productsApiMock.createProduct).mockResolvedValue({ data: { id: 1 } } as never)

      const ids = await seedQuickStartTutorialDbSamples()
      expect(ids.customerIds).toEqual([])
      expect(ids.productIds).toEqual([1, 1, 1, 1])
    })

    it('skips ids when createProduct throws', async () => {
      vi.mocked(customersApiMock.createCustomer).mockResolvedValue({ data: { id: 5 } } as never)
      vi.mocked(productsApiMock.createProduct).mockRejectedValue(new Error('dup'))

      const ids = await seedQuickStartTutorialDbSamples()
      expect(ids.customerIds).toEqual([5, 5])
      expect(ids.productIds).toEqual([])
    })

    it('skips ids when response has no id', async () => {
      vi.mocked(customersApiMock.createCustomer).mockResolvedValue({ data: {} } as never)
      vi.mocked(productsApiMock.createProduct).mockResolvedValue({ data: {} } as never)

      const ids = await seedQuickStartTutorialDbSamples()
      expect(ids.customerIds).toEqual([])
      expect(ids.productIds).toEqual([])
    })
  })

  describe('purgeQuickStartTutorialDbSamples', () => {
    it('deletes stored customers and products then clears ids', async () => {
      sessionStorage.setItem(
        'xcagi_tutorial_db_sample_ids',
        JSON.stringify({ customerIds: [1, 2], productIds: [3, 4] }),
      )
      vi.mocked(customersApiMock.batchDeleteCustomers).mockResolvedValue({} as never)
      vi.mocked(productsApiMock.batchDeleteProducts).mockResolvedValue({} as never)

      await purgeQuickStartTutorialDbSamples()
      expect(customersApiMock.batchDeleteCustomers).toHaveBeenCalledWith([1, 2])
      expect(productsApiMock.batchDeleteProducts).toHaveBeenCalledWith([3, 4])
      expect(sessionStorage.getItem('xcagi_tutorial_db_sample_ids')).toBeNull()
    })

    it('does not call batch delete when no ids stored', async () => {
      await purgeQuickStartTutorialDbSamples()
      expect(customersApiMock.batchDeleteCustomers).not.toHaveBeenCalled()
      expect(productsApiMock.batchDeleteProducts).not.toHaveBeenCalled()
    })

    it('continues when batch delete throws', async () => {
      sessionStorage.setItem(
        'xcagi_tutorial_db_sample_ids',
        JSON.stringify({ customerIds: [1], productIds: [2] }),
      )
      vi.mocked(customersApiMock.batchDeleteCustomers).mockRejectedValue(new Error('fail'))
      vi.mocked(productsApiMock.batchDeleteProducts).mockRejectedValue(new Error('fail'))

      await expect(purgeQuickStartTutorialDbSamples()).resolves.toBeUndefined()
      expect(sessionStorage.getItem('xcagi_tutorial_db_sample_ids')).toBeNull()
    })
  })

  describe('runQuickStartDeleteCustomersDemo', () => {
    it('runs without throwing when no UI present', async () => {
      vi.useFakeTimers()
      sessionStorage.setItem(
        'xcagi_tutorial_db_sample_ids',
        JSON.stringify({ customerIds: [10], productIds: [] }),
      )
      vi.mocked(customersApiMock.batchDeleteCustomers).mockResolvedValue({} as never)
      const promise = runQuickStartDeleteCustomersDemo()
      await vi.advanceTimersByTimeAsync(2000)
      await promise
      expect(customersApiMock.batchDeleteCustomers).toHaveBeenCalledWith([10])
      vi.useRealTimers()
    })
  })

  describe('runQuickStartDeleteProductsDemo', () => {
    it('runs without throwing when no UI present', async () => {
      vi.useFakeTimers()
      sessionStorage.setItem(
        'xcagi_tutorial_db_sample_ids',
        JSON.stringify({ customerIds: [], productIds: [20] }),
      )
      vi.mocked(productsApiMock.batchDeleteProducts).mockResolvedValue({} as never)
      const promise = runQuickStartDeleteProductsDemo()
      await vi.advanceTimersByTimeAsync(2000)
      await promise
      expect(productsApiMock.batchDeleteProducts).toHaveBeenCalledWith([20])
      expect(sessionStorage.getItem('xcagi_tutorial_db_sample_ids')).toBeNull()
      vi.useRealTimers()
    })
  })
})

describe('promptAdvancedTutorial', () => {
  describe('resolveRouteNameFromPath', () => {
    it('returns chat for empty path', () => {
      const router = { resolve: vi.fn() } as unknown as never
      expect(resolveRouteNameFromPath(router, '')).toBe('chat')
      expect(resolveRouteNameFromPath(router, '   ')).toBe('chat')
    })

    it('returns resolved route name', () => {
      const router = {
        resolve: vi.fn().mockReturnValue({ name: 'settings' }),
      } as unknown as never
      expect(resolveRouteNameFromPath(router, '/settings')).toBe('settings')
    })

    it('falls back to chat when resolve throws', () => {
      const router = {
        resolve: vi.fn().mockImplementation(() => {
          throw new Error('no route')
        }),
      } as unknown as never
      expect(resolveRouteNameFromPath(router, '/unknown')).toBe('chat')
    })

    it('falls back to chat when resolved name is empty', () => {
      const router = {
        resolve: vi.fn().mockReturnValue({ name: '' }),
      } as unknown as never
      expect(resolveRouteNameFromPath(router, '/x')).toBe('chat')
    })
  })

  describe('promptAdvancedTutorialAfterInstall', () => {
    it('returns already_completed when skipIfCompleted and tutorial completed', async () => {
      localStorage.setItem('xcagi_onboarding_driver_tutorial_completed', '1')
      const router = {} as never
      const ctx = { industryId: '', mods: [], visibleNav: [], isProMode: false, modMenuKeys: new Set() }
      const result = await promptAdvancedTutorialAfterInstall({
        router,
        buildContext: ctx,
      })
      expect(result).toBe('already_completed')
      localStorage.removeItem('xcagi_onboarding_driver_tutorial_completed')
    })

    it('returns dismissed when user declines confirm', async () => {
      localStorage.removeItem('xcagi_onboarding_driver_tutorial_completed')
      vi.mocked(appConfirmMock).mockResolvedValue(false)
      const router = {} as never
      const ctx = { industryId: '', mods: [], visibleNav: [], isProMode: false, modMenuKeys: new Set() }
      const result = await promptAdvancedTutorialAfterInstall({
        router,
        buildContext: ctx,
      })
      expect(result).toBe('dismissed')
    })
  })

  describe('launchAdvancedDriverTour', () => {
    it('starts the tour and returns active state', async () => {
      localStorage.removeItem('xcagi_onboarding_driver_tutorial_completed')
      const router = {
        push: vi.fn().mockResolvedValue(undefined),
      } as unknown as never
      const ctx = { industryId: '', mods: [], visibleNav: [], isProMode: false, modMenuKeys: new Set() }
      const result = await launchAdvancedDriverTour({
        router,
        buildContext: ctx,
        skipNavigation: true,
      })
      expect(typeof result).toBe('boolean')
    })
  })
})
