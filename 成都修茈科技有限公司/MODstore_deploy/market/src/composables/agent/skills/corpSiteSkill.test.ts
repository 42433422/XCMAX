import { describe, it, expect } from 'vitest'
import { matchCorpSiteIntent } from './corpSiteSkill'
import { CORP_LINKS } from '../../../content/siteKnowledge'
import type { AgentContext } from '../../../types/agent'

function ctx(message: string, route = '/index.html'): AgentContext {
  return {
    route,
    pageTitle: 'test',
    pageSummary: '',
    userMessage: message,
    history: [],
  }
}

describe('matchCorpSiteIntent', () => {
  it('matches contact intent', () => {
    const r = matchCorpSiteIntent(ctx('怎么联系你们？'))
    expect(r?.assistantReply).toContain(CORP_LINKS.contact)
  })

  it('matches products intent', () => {
    const r = matchCorpSiteIntent(ctx('你们有哪些产品？'))
    expect(r?.assistantReply).toContain(CORP_LINKS.services)
  })

  it('matches case manufacture', () => {
    const r = matchCorpSiteIntent(ctx('制造企业案例详情'))
    expect(r?.assistantReply).toContain(CORP_LINKS.caseManufacture)
  })

  it('matches news intent', () => {
    const r = matchCorpSiteIntent(ctx('有什么新闻动态？'))
    expect(r?.assistantReply).toContain(CORP_LINKS.news)
  })

  it('matches page intro on contact path', () => {
    const r = matchCorpSiteIntent(ctx('这个页面有什么功能？', '/contact.html'))
    expect(r?.assistantReply).toContain('联系')
  })

  it('returns null for unrelated query', () => {
    const r = matchCorpSiteIntent(ctx('今天天气怎么样'))
    expect(r).toBeNull()
  })
})
