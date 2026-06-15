import { describe, it, expect, beforeEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useOnboardingTutorialStore } from './onboardingTutorial'

vi.mock('@/tutorial/resolveSteps', () => ({
  resolveTrackSteps: vi.fn().mockReturnValue([
    { id: 'step1', target: '#el', content: 'Hello' },
  ]),
}))

vi.mock('@/tutorial/buildDriverSchedule', () => ({
  buildDriverScheduleFromTutorialSteps: vi.fn().mockReturnValue([
    { stepId: 'step1', driverStep: { element: '#el', popover: { title: 'Hi', description: 'Test' } } },
  ]),
}))

describe('useOnboardingTutorialStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    vi.clearAllMocks()
  })

  it('initializes with default state', () => {
    const store = useOnboardingTutorialStore()
    expect(store.active).toBe(false)
    expect(store.paused).toBe(false)
    expect(store.skipRequested).toBe(false)
    expect(store.schedules).toEqual([])
    expect(store.returnContext).toBeNull()
    expect(store.trackId).toBe('advanced')
  })

  it('isCompleted returns false when not completed', () => {
    const store = useOnboardingTutorialStore()
    expect(store.isCompleted()).toBe(false)
  })

  it('markCompleted sets localStorage', () => {
    const store = useOnboardingTutorialStore()
    store.markCompleted()
    expect(localStorage.getItem('xcagi_onboarding_driver_tutorial_completed')).toBe('1')
  })

  it('isCompleted returns true after markCompleted', () => {
    const store = useOnboardingTutorialStore()
    store.markCompleted()
    expect(store.isCompleted()).toBe(true)
  })

  it('start sets active and trackId', () => {
    const store = useOnboardingTutorialStore()
    store.start({
      track: 'basic',
      buildContext: { routeName: 'chat' } as any,
    })
    expect(store.trackId).toBe('basic')
    expect(store.active).toBe(true)
    expect(store.schedules.length).toBeGreaterThan(0)
  })

  it('start with default track', () => {
    const store = useOnboardingTutorialStore()
    store.start({
      buildContext: { routeName: 'chat' } as any,
    })
    expect(store.trackId).toBe('advanced')
  })

  it('start sets returnContext', () => {
    const store = useOnboardingTutorialStore()
    store.start({
      buildContext: { routeName: 'chat' } as any,
      returnContext: { routeName: 'settings' },
    })
    expect(store.returnContext).toEqual({ routeName: 'settings' })
  })

  it('finish with completed=true marks completed', () => {
    const store = useOnboardingTutorialStore()
    store.start({ buildContext: { routeName: 'chat' } as any })
    store.finish(true)
    expect(store.active).toBe(false)
    expect(store.schedules).toEqual([])
    expect(store.isCompleted()).toBe(true)
  })

  it('finish with completed=false does not mark completed', () => {
    const store = useOnboardingTutorialStore()
    store.start({ buildContext: { routeName: 'chat' } as any })
    store.finish(false)
    expect(store.active).toBe(false)
    expect(store.isCompleted()).toBe(false)
  })

  it('requestSkip sets skipRequested', () => {
    const store = useOnboardingTutorialStore()
    store.requestSkip()
    expect(store.skipRequested).toBe(true)
  })

  it('togglePause toggles paused state', () => {
    const store = useOnboardingTutorialStore()
    expect(store.paused).toBe(false)
    store.togglePause()
    expect(store.paused).toBe(true)
    store.togglePause()
    expect(store.paused).toBe(false)
  })
})
