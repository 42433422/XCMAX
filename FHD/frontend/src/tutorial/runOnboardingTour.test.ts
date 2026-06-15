import { describe, it, expect, vi, beforeEach } from 'vitest'
import { runOnboardingTour, type RunOnboardingTourOptions, type OnboardingTourStoreLike } from './runOnboardingTour'

vi.mock('driver.js', () => ({
  driver: vi.fn(() => ({
    highlight: vi.fn(),
    destroy: vi.fn(),
  })),
}))

vi.mock('driver.js/dist/driver.css', () => ({}))

vi.mock('@/tutorial/buildDriverSchedule', () => ({
  demoGroupCleanup: vi.fn(),
  waitForSelector: vi.fn().mockResolvedValue(null),
}))

vi.mock('@/tutorial/demoHelpers', () => ({
  getVirtualCursor: () => ({ hide: vi.fn() }),
  makeTimerGroup: () => ({}),
  sleep: vi.fn().mockResolvedValue(undefined),
}))

vi.mock('@/tutorial/assistantFloatTutorial', () => ({
  closeAssistantFloatPanelForTutorial: vi.fn(),
}))

vi.mock('@/tutorial/tutorialOfficeImportDemo', () => ({
  cleanupQuickStartImportDemo: vi.fn().mockResolvedValue(undefined),
}))

vi.mock('@/tutorial/tutorialDbSampleDemo', () => ({
  purgeQuickStartTutorialDbSamples: vi.fn().mockResolvedValue(undefined),
}))

vi.mock('@/composables/useTutorialSpeech', () => ({
  getTutorialSpeech: () => ({
    stop: vi.fn(),
    speak: vi.fn().mockResolvedValue(undefined),
    prefetchAll: vi.fn().mockResolvedValue(undefined),
    stepHoldMs: vi.fn().mockReturnValue(100),
  }),
}))

function makeMockStore(): OnboardingTourStoreLike {
  return {
    paused: false,
    skipRequested: false,
    requestSkip: vi.fn(),
    togglePause: vi.fn(),
  }
}

function makeMockRouter() {
  return {
    currentRoute: { value: { name: 'home', query: {} } },
    push: vi.fn().mockResolvedValue(undefined),
  } as unknown as Parameters<typeof runOnboardingTour>[0]['router']
}

describe('runOnboardingTour', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    document.body.classList.remove('tutorial-active')
  })

  it('calls onSkip when steps is empty', () => {
    const onSkip = vi.fn()
    const onComplete = vi.fn()
    const options: RunOnboardingTourOptions = {
      steps: [],
      router: makeMockRouter(),
      store: makeMockStore(),
      onComplete,
      onSkip,
    }
    const cleanup = runOnboardingTour(options)
    expect(onSkip).toHaveBeenCalled()
    expect(onComplete).not.toHaveBeenCalled()
    cleanup()
  })

  it('returns a cleanup function', () => {
    const options: RunOnboardingTourOptions = {
      steps: [
        {
          id: 'step-1',
          waitFor: '.test',
          title: 'Test',
          description: 'Test step',
          actionType: 'highlight',
          demo: () => ({ ok: true }),
          duration: 1000,
          isLast: false,
        },
      ],
      router: makeMockRouter(),
      store: makeMockStore(),
      onComplete: vi.fn(),
      onSkip: vi.fn(),
    }
    const cleanup = runOnboardingTour(options)
    expect(typeof cleanup).toBe('function')
    cleanup()
  })

  it('adds tutorial-active class to body', () => {
    const options: RunOnboardingTourOptions = {
      steps: [
        {
          id: 'step-1',
          waitFor: '.test',
          title: 'Test',
          description: 'Test step',
          actionType: 'highlight',
          demo: () => ({ ok: true }),
          duration: 1000,
          isLast: true,
        },
      ],
      router: makeMockRouter(),
      store: makeMockStore(),
      onComplete: vi.fn(),
      onSkip: vi.fn(),
    }
    const cleanup = runOnboardingTour(options)
    expect(document.body.classList.contains('tutorial-active')).toBe(true)
    cleanup()
  })

  it('removes tutorial-active class on cleanup', () => {
    const options: RunOnboardingTourOptions = {
      steps: [
        {
          id: 'step-1',
          waitFor: '.test',
          title: 'Test',
          description: 'Test step',
          actionType: 'highlight',
          demo: () => ({ ok: true }),
          duration: 1000,
          isLast: true,
        },
      ],
      router: makeMockRouter(),
      store: makeMockStore(),
      onComplete: vi.fn(),
      onSkip: vi.fn(),
    }
    const cleanup = runOnboardingTour(options)
    cleanup()
    expect(document.body.classList.contains('tutorial-active')).toBe(false)
  })

  it('handles skipRequested from store', async () => {
    const store = makeMockStore()
    store.skipRequested = true
    const onSkip = vi.fn()
    const options: RunOnboardingTourOptions = {
      steps: [
        {
          id: 'step-1',
          waitFor: '.test',
          title: 'Test',
          description: 'Test step',
          actionType: 'highlight',
          demo: () => ({ ok: true }),
          duration: 1000,
          isLast: false,
        },
      ],
      router: makeMockRouter(),
      store,
      onComplete: vi.fn(),
      onSkip,
    }
    const cleanup = runOnboardingTour(options)
    // Give the async tour a chance to check skipRequested
    await vi.waitFor(() => expect(onSkip).toHaveBeenCalled(), { timeout: 2000 })
    cleanup()
  })

  it('cleanup is idempotent', () => {
    const options: RunOnboardingTourOptions = {
      steps: [
        {
          id: 'step-1',
          waitFor: '.test',
          title: 'Test',
          description: 'Test step',
          actionType: 'highlight',
          demo: () => ({ ok: true }),
          duration: 1000,
          isLast: true,
        },
      ],
      router: makeMockRouter(),
      store: makeMockStore(),
      onComplete: vi.fn(),
      onSkip: vi.fn(),
    }
    const cleanup = runOnboardingTour(options)
    cleanup()
    cleanup() // should not throw
  })
})
