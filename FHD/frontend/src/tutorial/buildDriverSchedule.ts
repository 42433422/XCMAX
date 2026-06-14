import type { TutorialStep } from './types'
import {
  cursorClick,
  getVirtualCursor,
  highlightElement,
  safeClick,
  sleep,
  TUTORIAL_DEMO_SPEED,
  type DemoResult,
  type TimerGroup,
} from './demoHelpers'

const SPEED = TUTORIAL_DEMO_SPEED

const SELECTOR_TOUR_MAP: Record<string, string> = {
  '.sidebar .sidebar-menu': '[data-tour="sidebar-menu"]',
  '#view-chat .quick-actions': '[data-tour="chat-quick-actions"]',
  '#view-chat .chat-container': '[data-tour="chat-thread"]',
  '#view-chat .input-area': '[data-tour="chat-input-area"]',
  '[data-tour="store-nav-office"]': '[data-tour="store-nav-office"]',
  '[data-tour="ecosystem-launcher-modstore"]': '[data-tour="ecosystem-launcher-modstore"]',
  '[data-tour="store-one-click-install"]': '[data-tour="store-one-click-install"]',
  '[data-tour="store-shell"]': '[data-tour="store-shell"]',
}

export interface DriverStepSchedule {
  id: string
  title: string
  description: string
  routeName?: string
  routeQuery?: Record<string, string>
  waitFor: string
  actionType: 'click' | 'observe'
  duration: number
  isLast: boolean
  demo: (timers: TimerGroup) => DemoResult
}

function mapSelector(selector: string): string {
  const raw = String(selector || '').trim()
  if (!raw) return raw
  if (SELECTOR_TOUR_MAP[raw]) return SELECTOR_TOUR_MAP[raw]
  const navMatch = raw.match(/data-view="([^"]+)"/)
  if (navMatch && raw.includes('.sidebar')) {
    return `[data-tour="sidebar-${navMatch[1]}"]`
  }
  return raw
}

function resolveWaitFor(step: TutorialStep): string {
  const primary = mapSelector(step.highlightSelector || step.targetSelector)
  if (primary) return primary
  return mapSelector(step.targetSelector)
}

function demoForStep(step: TutorialStep, waitFor: string): (timers: TimerGroup) => DemoResult {
  if (step.id === 'office-pack-wait-ready') {
    return (timers) => {
      timers.set(() => {
        void (async () => {
          const { fetchEmployeePlannerStatus } = await import('@/utils/platformShellApi')
          const start = Date.now()
          while (Date.now() - start < 120_000) {
            try {
              const st = await fetchEmployeePlannerStatus(true)
              if (st.office_ready && st.registered_tool_count >= 1) return
            } catch {
              /* retry */
            }
            await sleep(1500)
          }
        })()
        const el = document.querySelector<HTMLElement>(waitFor)
        if (el) {
          getVirtualCursor()?.moveTo(el, { duration: 650 * SPEED, label: '安装中…' })
          highlightElement(el)
        }
      }, 400 * SPEED)
      return { ok: true }
    }
  }
  if (step.actionType === 'click') {
    return (timers) => {
      timers.set(() => {
        if (!safeClick(waitFor, `点这里`, 700 * SPEED)) {
          const legacy = document.querySelector<HTMLElement>(step.targetSelector)
          if (legacy) cursorClick(legacy, '点这里', 700 * SPEED)
        }
      }, 450 * SPEED)
      return { ok: true }
    }
  }
  return (timers) => {
    timers.set(() => {
      const el =
        document.querySelector<HTMLElement>(waitFor) ||
        document.querySelector<HTMLElement>(step.targetSelector)
      if (!el) return
      getVirtualCursor()?.moveTo(el, { duration: 650 * SPEED, label: '看这里' })
      highlightElement(el)
    }, 400 * SPEED)
    return { ok: true }
  }
}

export function buildDriverScheduleFromTutorialSteps(steps: TutorialStep[]): DriverStepSchedule[] {
  const list = steps.filter((s) => s?.id)
  return list.map((step, idx) => {
    const waitFor = resolveWaitFor(step)
    const isLast = idx >= list.length - 1
    const duration = step.actionType === 'click' ? 3200 * SPEED : 2800 * SPEED
    return {
      id: step.id,
      title: step.title,
      description: step.description,
      routeName: step.routeName?.trim() || undefined,
      routeQuery: step.routeQuery,
      waitFor,
      actionType: step.actionType,
      duration: isLast ? 86400000 : duration,
      isLast,
      demo: demoForStep(step, waitFor),
    }
  })
}

/** 轮询等待 selector 出现 */
export async function waitForSelector(
  selector: string,
  maxMs = 10000,
  intervalMs = 150,
): Promise<HTMLElement | null> {
  const sel = String(selector || '').trim()
  if (!sel) return null
  const start = Date.now()
  while (Date.now() - start < maxMs) {
    const el = document.querySelector<HTMLElement>(sel)
    if (el) {
      const rect = el.getBoundingClientRect()
      if (rect.width > 0 && rect.height > 0) return el
    }
    await sleep(intervalMs)
  }
  return null
}

export function demoGroupCleanup(timers: TimerGroup | null) {
  timers?.clear()
}
