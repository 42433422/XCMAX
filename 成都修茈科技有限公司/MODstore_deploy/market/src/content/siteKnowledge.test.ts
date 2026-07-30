import { describe, it, expect } from 'vitest'
import {
  resolveCorpPageId,
  getCorpQuickActions,
  getMarketQuickActions,
} from './siteKnowledge'

describe('siteKnowledge', () => {
  it('resolves corp page ids from pathname', () => {
    expect(resolveCorpPageId('/contact.html')).toBe('contact')
    expect(resolveCorpPageId('/case-manufacture.html')).toBe('case-manufacture')
    expect(resolveCorpPageId('/index.html')).toBe('home')
    expect(resolveCorpPageId('/developer.html')).toBe('developer')
    expect(resolveCorpPageId('/world-will.html')).toBe('world-will')
    expect(resolveCorpPageId('/download')).toBe('download')
  })

  it('gives unmapped pages a unique page id instead of home', () => {
    expect(resolveCorpPageId('/download-breakpoints.html')).toBe('download-breakpoints')
    expect(resolveCorpPageId('/download/goals')).toBe('download-goals')
    expect(resolveCorpPageId('/some-unknown-page.html')).toBe('page:some-unknown-page')
    expect(resolveCorpPageId('/some-unknown-page.html')).not.toBe('home')
  })

  it('provides at least 5 quick actions for corp home', () => {
    expect(getCorpQuickActions('/index.html').length).toBeGreaterThanOrEqual(5)
  })

  it('provides market-about quick actions', () => {
    expect(getMarketQuickActions('market-about').length).toBeGreaterThanOrEqual(5)
  })
})
