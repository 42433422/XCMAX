import { describe, expect, it } from 'vitest'
import { createModstoreI18n } from './i18n'

describe('modstore i18n', () => {
  it('returns Chinese messages by default', () => {
    const i18n = createModstoreI18n('zh-CN')
    expect(i18n.t('nav.refunds')).toBe('退款')
  })

  it('switches to English messages', () => {
    const i18n = createModstoreI18n('zh-CN')
    i18n.setLocale('en-US')
    expect(i18n.t('nav.refunds')).toBe('Refunds')
  })
})
