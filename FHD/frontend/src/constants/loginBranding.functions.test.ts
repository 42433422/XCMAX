import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('../../package.json', () => ({ default: { version: '10.0.0' } }))

import {
  XCAGI_VERSION_LABEL,
  normalizeLoginSku,
  loginEyebrow,
  loginSubtitle,
  loginUsernamePlaceholder,
  loginAccountInputPlaceholder,
  loginPasswordInputPlaceholder,
  marketBaseUrl,
  marketRegisterUrl,
  marketForgotPasswordUrl,
  loginHelpDocUrl,
  loginPageTitle,
  LOGIN_HELP_PAGE_TITLE,
  LOGIN_HELP_SECTIONS,
} from './loginBranding'

describe('loginBranding constants and functions', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  describe('XCAGI_VERSION_LABEL', () => {
    it('derives version label from package.json major version', () => {
      expect(XCAGI_VERSION_LABEL).toBe('V10')
    })
  })

  describe('normalizeLoginSku', () => {
    it('returns enterprise for enterprise input', () => {
      expect(normalizeLoginSku('enterprise')).toBe('enterprise')
    })

    it('returns personal for personal input', () => {
      expect(normalizeLoginSku('personal')).toBe('personal')
    })

    it('returns generic for unknown input', () => {
      expect(normalizeLoginSku('unknown')).toBe('generic')
    })

    it('returns generic for null input', () => {
      expect(normalizeLoginSku(null)).toBe('generic')
    })

    it('returns generic for undefined input', () => {
      expect(normalizeLoginSku(undefined)).toBe('generic')
    })

    it('returns generic for empty string', () => {
      expect(normalizeLoginSku('')).toBe('generic')
    })

    it('normalizes to lowercase', () => {
      expect(normalizeLoginSku('ENTERPRISE')).toBe('enterprise')
    })

    it('trims whitespace', () => {
      expect(normalizeLoginSku('  enterprise  ')).toBe('enterprise')
    })

    it('returns generic for non-matching string', () => {
      expect(normalizeLoginSku('custom-sku')).toBe('generic')
    })
  })

  describe('loginEyebrow', () => {
    it('returns enterprise eyebrow with version', () => {
      expect(loginEyebrow('enterprise')).toContain('企业版')
      expect(loginEyebrow('enterprise')).toContain(XCAGI_VERSION_LABEL)
    })

    it('returns personal eyebrow with version', () => {
      expect(loginEyebrow('personal')).toContain('个人版')
      expect(loginEyebrow('personal')).toContain(XCAGI_VERSION_LABEL)
    })

    it('returns generic eyebrow with version', () => {
      expect(loginEyebrow('generic')).toContain('XCAGI')
      expect(loginEyebrow('generic')).toContain(XCAGI_VERSION_LABEL)
    })

    it('normalizes sku before lookup', () => {
      expect(loginEyebrow('ENTERPRISE')).toContain('企业版')
    })
  })

  describe('loginSubtitle', () => {
    it('returns enterprise subtitle', () => {
      expect(loginSubtitle('enterprise')).toBe('使用修茈市场账号登录')
    })

    it('returns personal subtitle', () => {
      expect(loginSubtitle('personal')).toBe('本地账号登录')
    })

    it('returns generic subtitle', () => {
      expect(loginSubtitle('generic')).toBe('登录进入工作台')
    })

    it('normalizes sku before lookup', () => {
      expect(loginSubtitle('PERSONAL')).toBe('本地账号登录')
    })
  })

  describe('loginUsernamePlaceholder', () => {
    it('returns market account for enterprise', () => {
      expect(loginUsernamePlaceholder('enterprise')).toBe('市场账号')
    })

    it('returns generic account for personal', () => {
      expect(loginUsernamePlaceholder('personal')).toBe('账号')
    })

    it('returns generic account for generic', () => {
      expect(loginUsernamePlaceholder('generic')).toBe('账号')
    })
  })

  describe('loginAccountInputPlaceholder', () => {
    it('returns market account or email for enterprise', () => {
      expect(loginAccountInputPlaceholder('enterprise')).toBe('市场账号或邮箱')
    })

    it('returns local account for personal', () => {
      expect(loginAccountInputPlaceholder('personal')).toBe('本地账号')
    })

    it('returns generic account for generic', () => {
      expect(loginAccountInputPlaceholder('generic')).toBe('账号')
    })

    it('normalizes sku before lookup', () => {
      expect(loginAccountInputPlaceholder('ENTERPRISE')).toBe('市场账号或邮箱')
    })
  })

  describe('loginPasswordInputPlaceholder', () => {
    it('returns password label', () => {
      expect(loginPasswordInputPlaceholder()).toBe('密码')
    })
  })

  describe('marketBaseUrl', () => {
    it('returns default market base url', () => {
      const url = marketBaseUrl()
      expect(url).toContain('xiu-ci.com/market')
      expect(url).not.toMatch(/\/$/)
    })
  })

  describe('marketRegisterUrl', () => {
    it('appends register path to market base', () => {
      const url = marketRegisterUrl()
      expect(url).toMatch(/\/register$/)
    })
  })

  describe('marketForgotPasswordUrl', () => {
    it('appends forgot-password path to market base', () => {
      const url = marketForgotPasswordUrl()
      expect(url).toMatch(/\/forgot-password$/)
    })
  })

  describe('loginHelpDocUrl', () => {
    it('returns string value from env', () => {
      const url = loginHelpDocUrl()
      expect(typeof url).toBe('string')
    })
  })

  describe('loginPageTitle', () => {
    it('combines eyebrow with login suffix', () => {
      const title = loginPageTitle('enterprise')
      expect(title).toContain('企业版')
      expect(title).toContain('登录')
    })

    it('works for personal sku', () => {
      const title = loginPageTitle('personal')
      expect(title).toContain('个人版')
      expect(title).toContain('登录')
    })

    it('works for generic sku', () => {
      const title = loginPageTitle('generic')
      expect(title).toContain('XCAGI')
      expect(title).toContain('登录')
    })
  })

  describe('LOGIN_HELP_PAGE_TITLE', () => {
    it('is a non-empty string', () => {
      expect(typeof LOGIN_HELP_PAGE_TITLE).toBe('string')
      expect(LOGIN_HELP_PAGE_TITLE.length).toBeGreaterThan(0)
    })
  })

  describe('LOGIN_HELP_SECTIONS', () => {
    it('is an array of sections', () => {
      expect(Array.isArray(LOGIN_HELP_SECTIONS)).toBe(true)
      expect(LOGIN_HELP_SECTIONS.length).toBeGreaterThan(0)
    })

    it('each section has title and items', () => {
      for (const section of LOGIN_HELP_SECTIONS) {
        expect(section).toHaveProperty('title')
        expect(typeof section.title).toBe('string')
        expect(section).toHaveProperty('items')
        expect(Array.isArray(section.items)).toBe(true)
        expect(section.items.length).toBeGreaterThan(0)
      }
    })
  })
})
