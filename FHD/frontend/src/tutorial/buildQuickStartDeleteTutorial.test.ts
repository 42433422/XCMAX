import { describe, expect, it } from 'vitest'
import { buildQuickStartDeleteTutorialSteps } from './buildQuickStartDeleteTutorial'
import type { VisibleNavItem } from '@/composables/useVisibleNavItems'

const nav = (keys: Array<{ key: string; name: string }>): VisibleNavItem[] =>
  keys.map((k) => ({
    key: k.key,
    name: k.name,
    routeName: k.key,
    source: 'core',
  }))

describe('buildQuickStartDeleteTutorialSteps', () => {
  it('returns empty when customers and products are absent', () => {
    expect(buildQuickStartDeleteTutorialSteps(nav([{ key: 'chat', name: '对话' }]))).toEqual([])
  })

  it('includes department and personnel delete steps when nav present', () => {
    const steps = buildQuickStartDeleteTutorialSteps(
      nav([
        { key: 'products', name: '人员管理' },
        { key: 'customers', name: '部门管理' },
      ]),
    )
    const ids = steps.map((s) => s.id)
    expect(ids).toContain('quickstart-import-seed-db')
    expect(ids).toContain('quickstart-delete-customers-nav')
    expect(ids).toContain('quickstart-delete-customers')
    expect(ids).toContain('quickstart-delete-products-nav')
    expect(ids).toContain('quickstart-delete-products')
    expect(steps.slice(-3).map((step) => step.targetSelector)).toEqual([
      '#view-chat [data-tutorial-id="chat-side-panel-toggle"][aria-expanded="false"]',
      '#chat-side-panel [data-tutorial-id="chat-conversation-tab"][aria-selected="false"]',
      '#chat-side-panel #newConversationBtn',
    ])
  })
})
