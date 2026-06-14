import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

const resolveTrackSteps = vi.fn()
const resolveAllWarmupSteps = vi.fn(() => [
  { id: 'w1', description: '热身一' },
  { id: 'w2', description: '热身一' },
  { id: 'w3', description: '' },
  { id: 'w4', description: '热身二' },
])
const resolveStepHighlightRect = vi.fn(() => ({ top: 1, left: 2, width: 3, height: 4 }))

vi.mock('@/tutorial/buildContext', () => ({
  createTutorialBuildContext: () => ({ industryId: '考勤', mods: [], visibleNav: [], isProMode: false }),
}))
vi.mock('@/tutorial/catalog', () => ({
  getTrackLabel: () => '基础教程',
}))
vi.mock('@/tutorial/resolveSteps', () => ({
  resolveTrackSteps: (...a: unknown[]) => resolveTrackSteps(...a),
  resolveAllWarmupSteps: (...a: unknown[]) => resolveAllWarmupSteps(...a),
}))
vi.mock('@/tutorial/runtime', () => ({
  bindTutorialRouter: vi.fn(),
  dispatchAssistantTab: vi.fn(),
  afterAssistantTabLayout: (cb: () => void) => cb(),
  ensureRouteForStepThen: (_s: unknown, cb: () => void) => cb(),
  getTutorialFallbackHighlightRect: () => ({ top: 0, left: 0, width: 10, height: 10 }),
  resolveStepHighlightRect: (...a: unknown[]) => resolveStepHighlightRect(...a),
  shouldNeverAutoSkipStep: () => false,
}))

import {
  useTutorialStore,
  getTutorialTtsWarmupTexts,
} from './tutorial'

const baseSteps = [
  { id: 's1', actionType: 'observe' },
  { id: 's2', actionType: 'click' },
  { id: 's3', actionType: 'observe' },
]

describe('tutorial store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    resolveTrackSteps.mockReset()
    resolveStepHighlightRect.mockReturnValue({ top: 1, left: 2, width: 3, height: 4 })
    window.__XCAGI_IS_PRO_MODE = false
  })

  it('getTutorialTtsWarmupTexts dedupes and drops empty', () => {
    const out = getTutorialTtsWarmupTexts(false)
    expect(out).toEqual(['热身一', '热身二'])
  })

  it('startTutorial loads steps and resolves first observe step', () => {
    resolveTrackSteps.mockReturnValue(baseSteps)
    const s = useTutorialStore()
    s.startTutorial({ track: 'basic' })
    expect(s.isActive).toBe(true)
    expect(s.steps).toHaveLength(3)
    expect(s.currentStep?.id).toBe('s1')
    expect(s.canNext).toBe(true)
    expect(s.testResults.s1).toBe('passed')
  })

  it('navigation: next, click step, prev', () => {
    resolveTrackSteps.mockReturnValue(baseSteps)
    const s = useTutorialStore()
    s.startTutorial({ track: 'basic' })
    s.nextStep()
    expect(s.currentStep?.id).toBe('s2')
    s.blockOutsideClick()
    expect(s.blockedTip).toContain('请先点击')
    s.markCurrentStepClicked()
    expect(s.canNext).toBe(true)
    expect(s.testResults.s2).toBe('passed')
    s.prevStep()
    expect(s.currentStep?.id).toBe('s1')
    expect(s.hasPrev).toBe(false)
  })

  it('nextStep on last step finishes tutorial', () => {
    resolveTrackSteps.mockReturnValue(baseSteps)
    const s = useTutorialStore()
    s.startTutorial({ track: 'basic' })
    s.nextStep()
    s.nextStep()
    expect(s.currentStep?.id).toBe('s3')
    expect(s.isLastStep).toBe(true)
    s.nextStep()
    expect(s.isActive).toBe(false)
    expect(s.lastTestReport?.total).toBe(3)
  })

  it('startTutorial finishes immediately when no steps', () => {
    resolveTrackSteps.mockReturnValue([])
    const s = useTutorialStore()
    s.startTutorial({ track: 'basic' })
    expect(s.isActive).toBe(false)
  })

  it('pro basic falls back to advanced track', () => {
    resolveTrackSteps.mockImplementation((track: string) => (track === 'advanced' ? baseSteps : []))
    const s = useTutorialStore()
    s.startTutorial({ track: 'basic', isProMode: true })
    expect(s.proBasicFallbackNotice).toContain('进阶教程')
    expect(s.currentTrack).toBe('advanced')
  })

  it('exitTutorial sets exited flag', () => {
    resolveTrackSteps.mockReturnValue(baseSteps)
    const s = useTutorialStore()
    s.startTutorial({ track: 'basic' })
    s.exitTutorial()
    expect(s.isExited).toBe(true)
    expect(s.isActive).toBe(false)
  })

  it('testSummary counts pending/passed/skipped', () => {
    resolveTrackSteps.mockReturnValue(baseSteps)
    const s = useTutorialStore()
    s.startTutorial({ track: 'basic' })
    const sum = s.testSummary
    expect(sum.total).toBe(3)
    expect(sum.passed).toBeGreaterThanOrEqual(1)
  })

  it('currentTrackLabel reads track label', () => {
    resolveTrackSteps.mockReturnValue(baseSteps)
    const s = useTutorialStore()
    s.startTutorial({ track: 'basic' })
    expect(s.currentTrackLabel).toBe('基础教程')
  })

  it('refreshHighlight no-op when inactive', () => {
    const s = useTutorialStore()
    s.refreshHighlight()
    expect(s.highlightRect).toBeNull()
  })
})
