import { describe, expect, it, vi } from 'vitest'
import { buildDriverScheduleFromTutorialSteps } from './buildDriverSchedule'
import { makeTimerGroup } from './demoHelpers'
import type { TutorialStep } from './types'

describe('buildDriverScheduleFromTutorialSteps', () => {
  it('maps sidebar nav steps to data-tour selectors', () => {
    const steps: TutorialStep[] = [
      {
        id: 'nav-chat',
        title: '智能对话',
        description: '进入对话页',
        targetSelector: '.sidebar .menu-item[data-view="chat"]',
        actionType: 'click',
      },
    ]
    const schedule = buildDriverScheduleFromTutorialSteps(steps)
    expect(schedule[0].waitFor).toBe('[data-tour="sidebar-chat"]')
    expect(schedule[0].actionType).toBe('click')
  })

  it('marks last step with long duration for manual finish', () => {
    const steps: TutorialStep[] = [
      {
        id: 'a',
        title: 'A',
        description: 'd',
        targetSelector: '[data-tour="sidebar-menu"]',
        actionType: 'observe',
      },
      {
        id: 'b',
        title: 'B',
        description: 'd',
        targetSelector: '[data-tour="chat-thread"]',
        actionType: 'observe',
        routeName: 'chat',
      },
    ]
    const schedule = buildDriverScheduleFromTutorialSteps(steps)
    expect(schedule[1].isLast).toBe(true)
    expect(schedule[1].duration).toBeGreaterThan(100000)
  })

  it('passes mod-store tour selectors and route query', () => {
    const steps: TutorialStep[] = [
      {
        id: 'office-pack-open-modstore',
        title: '员工商店',
        description: 'd',
        targetSelector: '[data-tour="ecosystem-launcher-modstore"]',
        actionType: 'click',
        routeName: 'ai-ecosystem',
      },
      {
        id: 'office-pack-nav-tab',
        title: '办公员工包',
        description: 'd',
        targetSelector: '[data-tour="store-nav-office"]',
        actionType: 'click',
        routeName: 'mod-store',
        routeQuery: { tab: 'office' },
      },
    ]
    const schedule = buildDriverScheduleFromTutorialSteps(steps)
    expect(schedule[0].waitFor).toBe('[data-tour="ecosystem-launcher-modstore"]')
    expect(schedule[1].waitFor).toBe('[data-tour="store-nav-office"]')
    expect(schedule[1].routeQuery).toEqual({ tab: 'office' })
  })
})

describe('makeTimerGroup', () => {
  it('clears pending timers', () => {
    vi.useFakeTimers()
    const timers = makeTimerGroup()
    let hit = 0
    timers.set(() => {
      hit += 1
    }, 500)
    timers.clear()
    vi.advanceTimersByTime(600)
    expect(hit).toBe(0)
    vi.useRealTimers()
  })
})
