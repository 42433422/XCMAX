import { describe, it, expect, vi } from 'vitest'
import {
  normalizeLoginSku,
  loginEyebrow,
  loginSubtitle,
  loginUsernamePlaceholder,
  loginAccountInputPlaceholder,
  loginPasswordInputPlaceholder,
  marketRegisterUrl,
  marketForgotPasswordUrl,
  loginHelpDocUrl,
  loginPageTitle,
  XCAGI_VERSION_LABEL,
  LOGIN_HELP_PAGE_TITLE,
  LOGIN_HELP_SECTIONS,
} from './loginBranding'

describe('loginBranding', () => {
  describe('normalizeLoginSku', () => {
    it('returns enterprise for enterprise', () => {
      expect(normalizeLoginSku('enterprise')).toBe('enterprise')
    })

    it('returns personal for personal', () => {
      expect(normalizeLoginSku('personal')).toBe('personal')
    })

    it('returns generic for unknown', () => {
      expect(normalizeLoginSku('unknown')).toBe('generic')
    })

    it('returns generic for null', () => {
      expect(normalizeLoginSku(null)).toBe('generic')
    })

    it('returns generic for undefined', () => {
      expect(normalizeLoginSku(undefined)).toBe('generic')
    })

    it('returns generic for empty string', () => {
      expect(normalizeLoginSku('')).toBe('generic')
    })

    it('normalizes case (uppercase)', () => {
      expect(normalizeLoginSku('ENTERPRISE')).toBe('enterprise')
    })

    it('trims whitespace', () => {
      expect(normalizeLoginSku('  enterprise  ')).toBe('enterprise')
    })
  })

  describe('loginEyebrow', () => {
    it('returns enterprise eyebrow', () => {
      expect(loginEyebrow('enterprise')).toContain('企业版')
      expect(loginEyebrow('enterprise')).toContain(XCAGI_VERSION_LABEL)
    })

    it('returns personal eyebrow', () => {
      expect(loginEyebrow('personal')).toContain('个人版')
    })

    it('returns generic eyebrow', () => {
      expect(loginEyebrow('generic')).toContain('XCAGI')
      expect(loginEyebrow('generic')).not.toContain('企业版')
      expect(loginEyebrow('generic')).not.toContain('个人版')
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
  })

  describe('loginUsernamePlaceholder', () => {
    it('returns 市场账号 for enterprise', () => {
      expect(loginUsernamePlaceholder('enterprise')).toBe('市场账号')
    })

    it('returns 账号 for non-enterprise', () => {
      expect(loginUsernamePlaceholder('personal')).toBe('账号')
      expect(loginUsernamePlaceholder('generic')).toBe('账号')
    })
  })

  describe('loginAccountInputPlaceholder', () => {
    it('returns enterprise placeholder', () => {
      expect(loginAccountInputPlaceholder('enterprise')).toBe('市场账号或邮箱')
    })

    it('returns personal placeholder', () => {
      expect(loginAccountInputPlaceholder('personal')).toBe('本地账号')
    })

    it('returns generic placeholder', () => {
      expect(loginAccountInputPlaceholder('generic')).toBe('账号')
    })
  })

  describe('loginPasswordInputPlaceholder', () => {
    it('returns 密码', () => {
      expect(loginPasswordInputPlaceholder()).toBe('密码')
    })
  })

  describe('marketRegisterUrl', () => {
    it('returns a URL ending with /register', () => {
      expect(marketRegisterUrl()).toMatch(/\/register$/)
    })
  })

  describe('marketForgotPasswordUrl', () => {
    it('returns a URL ending with /forgot-password', () => {
      expect(marketForgotPasswordUrl()).toMatch(/\/forgot-password$/)
    })
  })

  describe('loginHelpDocUrl', () => {
    it('returns a string', () => {
      expect(typeof loginHelpDocUrl()).toBe('string')
    })
  })

  describe('loginPageTitle', () => {
    it('returns title with eyebrow and 登录', () => {
      const title = loginPageTitle('enterprise')
      expect(title).toContain('登录')
      expect(title).toContain('企业版')
    })

    it('returns generic title', () => {
      const title = loginPageTitle('generic')
      expect(title).toContain('登录')
    })
  })

  describe('LOGIN_HELP_SECTIONS', () => {
    it('is an array with sections', () => {
      expect(Array.isArray(LOGIN_HELP_SECTIONS)).toBe(true)
      expect(LOGIN_HELP_SECTIONS.length).toBeGreaterThan(0)
    })

    it('each section has title and items', () => {
      for (const section of LOGIN_HELP_SECTIONS) {
        expect(section).toHaveProperty('title')
        expect(section).toHaveProperty('items')
        expect(Array.isArray(section.items)).toBe(true)
      }
    })
  })

  describe('LOGIN_HELP_PAGE_TITLE', () => {
    it('is a non-empty string', () => {
      expect(typeof LOGIN_HELP_PAGE_TITLE).toBe('string')
      expect(LOGIN_HELP_PAGE_TITLE.length).toBeGreaterThan(0)
    })
  })
})
