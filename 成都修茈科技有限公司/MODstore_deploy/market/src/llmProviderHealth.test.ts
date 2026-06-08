import { describe, expect, it } from 'vitest'

import {

  catalogIssueCreditHint,

  classifyLlmCatalogIssue,

  hasAnyLlmKey,

  walletTileKeyConfigured,

} from './llmProviderHealth'



describe('llmProviderHealth', () => {

  it('hasAnyLlmKey: runtime key present if BYOK saved or platform env set', () => {

    expect(hasAnyLlmKey(null)).toBe(false)

    expect(hasAnyLlmKey({ has_platform_key: true })).toBe(true)

    expect(hasAnyLlmKey({ provider: 'openai', has_platform_key: true })).toBe(true)

    expect(hasAnyLlmKey({ provider: 'xiaomi', has_platform_key: true })).toBe(true)

    expect(hasAnyLlmKey({ has_user_override: true })).toBe(true)

  })



  it('walletTileKeyConfigured: magnetic lit on BYOK, or Xiaomi platform-only', () => {

    expect(walletTileKeyConfigured('openai', { has_platform_key: true, has_user_override: false })).toBe(false)

    expect(walletTileKeyConfigured('minimax', { has_platform_key: true, has_user_override: false })).toBe(false)

    expect(walletTileKeyConfigured('xiaomi', { has_platform_key: true, has_user_override: false })).toBe(true)

    expect(walletTileKeyConfigured('openai', { has_platform_key: false, has_user_override: true })).toBe(true)

    expect(walletTileKeyConfigured('openai', null)).toBe(false)

  })



  it('classifies authentication and transient catalog issues', () => {

    expect(classifyLlmCatalogIssue('401 invalid api key', '')).toBe('danger')

    expect(classifyLlmCatalogIssue('402 payment required', 'remote')).toBe('danger')

    expect(classifyLlmCatalogIssue('402 payment required', 'static_fallback_merged')).toBe('warn')

    expect(classifyLlmCatalogIssue('access token expired', '')).toBe('expired')

    expect(classifyLlmCatalogIssue('平台密钥已过期，请重新配置', '')).toBe('expired')

    expect(classifyLlmCatalogIssue('timeout while fetching models', '')).toBe('warn')

    expect(classifyLlmCatalogIssue('', 'fallback_after_error')).toBe('warn')

    expect(classifyLlmCatalogIssue('catalog_static_fallback_only', 'static_fallback_merged')).toBe('warn')

    expect(classifyLlmCatalogIssue('model list empty', '')).toBeNull()

  })



  it('catalogIssueCreditHint for billing-ish errors', () => {

    expect(catalogIssueCreditHint('http 402')).toContain('额度')

    expect(catalogIssueCreditHint('insufficient_quota')).toContain('额度')

    expect(catalogIssueCreditHint('401 unauthorized')).toBeNull()

    expect(catalogIssueCreditHint('')).toBeNull()

  })

})

