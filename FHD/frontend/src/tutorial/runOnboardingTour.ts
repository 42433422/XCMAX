import { driver, type Driver } from 'driver.js'
import 'driver.js/dist/driver.css'
import type { Router } from 'vue-router'
import {
  demoGroupCleanup,
  type DriverStepSchedule,
  waitForSelector,
} from '@/tutorial/buildDriverSchedule'
import { getVirtualCursor, makeTimerGroup, sleep, type TimerGroup } from '@/tutorial/demoHelpers'

export type OnboardingTourStoreLike = {
  paused: boolean
  skipRequested: boolean
  requestSkip: () => void
  togglePause: () => void
}

export type RunOnboardingTourOptions = {
  steps: DriverStepSchedule[]
  router: Router
  store: OnboardingTourStoreLike
  onComplete: () => void
  onSkip: () => void
}

export function runOnboardingTour(options: RunOnboardingTourOptions): () => void {
  const { steps, router, store, onComplete, onSkip } = options
  if (!steps.length) {
    onSkip()
    return () => {}
  }

  let destroyed = false
  let timers: TimerGroup | null = makeTimerGroup()
  let driverRef: Driver | null = null
  let running = false

  const cleanup = () => {
    destroyed = true
    demoGroupCleanup(timers)
    timers = null
    getVirtualCursor()?.hide()
    document.body.classList.remove('tutorial-active')
    try {
      driverRef?.destroy()
    } catch {
      /* ignore */
    }
    driverRef = null
  }

  const mountControls = (popoverEl: Element) => {
    const footer =
      popoverEl.querySelector('.driver-popover-footer') ||
      popoverEl.querySelector('.driver-popover-navigation-btns')
    if (!footer || footer.querySelector('.xcagi-tour-extra-controls')) return
    const wrap = document.createElement('div')
    wrap.className = 'xcagi-tour-extra-controls'
    const pauseBtn = document.createElement('button')
    pauseBtn.type = 'button'
    pauseBtn.className = 'xcagi-tour-btn xcagi-tour-btn-pause'
    pauseBtn.textContent = store.paused ? '继续' : '暂停'
    pauseBtn.addEventListener('click', () => {
      store.togglePause()
      pauseBtn.textContent = store.paused ? '继续' : '暂停'
    })
    const skipBtn = document.createElement('button')
    skipBtn.type = 'button'
    skipBtn.className = 'xcagi-tour-btn xcagi-tour-btn-skip'
    skipBtn.textContent = '跳过教程'
    skipBtn.addEventListener('click', () => {
      store.requestSkip()
    })
    wrap.appendChild(pauseBtn)
    wrap.appendChild(skipBtn)
    footer.appendChild(wrap)
  }

  driverRef = driver({
    showProgress: true,
    showButtons: [],
    overlayColor: 'rgba(15, 23, 42, 0.55)',
    popoverClass: 'xcagi-tour-popover',
    stagePadding: 8,
    onPopoverRender: (popover) => {
      mountControls(popover.wrapper)
    },
    onDestroyStarted: () => {
      if (!destroyed) cleanup()
    },
  })

  document.body.classList.add('tutorial-active')

  const navigateIfNeeded = async (routeName?: string, routeQuery?: Record<string, string>) => {
    const name = String(routeName || '').trim()
    if (!name) return
    const current = String(router.currentRoute.value.name || '')
    const query = routeQuery || {}
    const sameRoute = current === name
    const sameQuery = Object.entries(query).every(
      ([k, v]) => String(router.currentRoute.value.query[k] || '') === String(v),
    )
    if (sameRoute && sameQuery) return
    try {
      await router.push({ name, query })
    } catch {
      /* ignore */
    }
    await sleep(320)
  }

  const waitWithPause = async (ms: number) => {
    const end = Date.now() + ms
    while (Date.now() < end) {
      if (destroyed || store.skipRequested) return false
      if (store.paused) {
        await sleep(120)
        continue
      }
      await sleep(Math.min(120, end - Date.now()))
    }
    return !destroyed && !store.skipRequested
  }

  const runStep = async (idx: number) => {
    if (destroyed || store.skipRequested) {
      cleanup()
      onSkip()
      return
    }
    const step = steps[idx]
    if (!step) {
      cleanup()
      onComplete()
      return
    }

    await navigateIfNeeded(step.routeName, step.routeQuery)

    let el = await waitForSelector(step.waitFor)
    if (!el && step.actionType === 'click') {
      await sleep(400)
      el = await waitForSelector(step.waitFor, 6000)
    }

    if (el && driverRef) {
      driverRef.highlight({
        element: el,
        popover: {
          title: step.title,
          description: step.description,
          side: 'bottom',
          align: 'start',
        },
      })
      mountControls(document.querySelector('.driver-popover') || document.body)
    }

    demoGroupCleanup(timers)
    timers = makeTimerGroup()
    const result = step.demo(timers)
    if (!result.ok && result.fallbackMsg && driverRef && el) {
      driverRef.highlight({
        element: el,
        popover: {
          title: step.title,
          description: result.fallbackMsg,
          side: 'bottom',
          align: 'start',
        },
      })
    }

    if (step.isLast) {
      const cta = document.querySelector('.xcagi-tour-extra-controls')
      if (cta && !cta.querySelector('.xcagi-tour-btn-finish')) {
        const finishBtn = document.createElement('button')
        finishBtn.type = 'button'
        finishBtn.className = 'xcagi-tour-btn xcagi-tour-btn-finish'
        finishBtn.textContent = '完成，开始使用'
        finishBtn.addEventListener('click', () => {
          cleanup()
          onComplete()
        })
        cta.appendChild(finishBtn)
      }
      return
    }

    const ok = await waitWithPause(step.duration)
    if (!ok) {
      cleanup()
      onSkip()
      return
    }
    await runStep(idx + 1)
  }

  if (!running) {
    running = true
    void runStep(0)
  }

  return cleanup
}
