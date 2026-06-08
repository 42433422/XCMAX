import { describe, it, expect } from 'vitest'
import {
  getCorpQuickActions,
  getCorpWelcomeTitle,
  resolveCorpPageId,
} from './siteKnowledge'

describe('siteKnowledge corp welcome', () => {
  it('resolves services page and returns KiKi quick actions', () => {
    expect(resolveCorpPageId('/services.html')).toBe('services')
    const actions = getCorpQuickActions('/services.html')
    expect(actions.length).toBeGreaterThanOrEqual(4)
    expect(actions.some((a) => a.label.includes('Excel'))).toBe(true)
    expect(actions.some((a) => a.task === 'navigate')).toBe(true)
  })

  it('returns page-specific welcome title on home', () => {
    const title = getCorpWelcomeTitle('/index.html')
    expect(title).toContain('修茈')
    expect(title).not.toBe('')
  })

  it('contact page keeps intake tasks', () => {
    const actions = getCorpQuickActions('/contact.html')
    expect(actions.some((a) => a.task === 'intake_fill')).toBe(true)
    expect(getCorpWelcomeTitle('/contact.html')).toContain('问卷')
  })
})
