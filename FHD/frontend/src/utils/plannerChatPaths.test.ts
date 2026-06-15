import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { LS_PLANNER_MOD_FACADE_ENABLED } from '@/constants/plannerMod'
import { invalidateTenantStorageScopeCache } from '@/utils/tenantStorageScope'
import {
  resolvePlannerChatPath,
  resolvePlannerChatStreamPath,
  resolvePlannerChatBatchPath,
  resolvePlannerUnifiedChatPath,
  resolvePlannerIntentTestPath,
} from './plannerChatPaths'

describe('plannerChatPaths', () => {
  beforeEach(() => {
    invalidateTenantStorageScopeCache()
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('uses host paths when facade off', () => {
    vi.stubGlobal('localStorage', { getItem: () => null })
    expect(resolvePlannerChatPath()).toBe('/api/ai/chat')
    expect(resolvePlannerChatStreamPath()).toBe('/api/ai/chat/stream')
    expect(resolvePlannerChatBatchPath()).toBe('/api/ai/chat/batch')
    expect(resolvePlannerUnifiedChatPath()).toBe('/api/ai/unified_chat')
    expect(resolvePlannerIntentTestPath()).toBe('/api/ai/intent/test')
  })

  it('uses mod paths when facade on', () => {
    const store: Record<string, string> = { [LS_PLANNER_MOD_FACADE_ENABLED]: '1' }
    vi.stubGlobal('localStorage', { getItem: (k: string) => store[k] ?? null })
    expect(resolvePlannerChatPath()).toBe('/api/mod/xcagi-planner-bridge/chat')
    expect(resolvePlannerChatStreamPath()).toBe('/api/mod/xcagi-planner-bridge/chat/stream')
    expect(resolvePlannerChatBatchPath()).toBe('/api/mod/xcagi-planner-bridge/chat/batch')
    expect(resolvePlannerUnifiedChatPath()).toBe('/api/mod/xcagi-planner-bridge/unified_chat')
    expect(resolvePlannerIntentTestPath()).toBe('/api/mod/xcagi-planner-bridge/intent/test')
  })

  it('respects VITE_CHAT_STREAM_PATH when facade off', () => {
    vi.stubGlobal('localStorage', { getItem: () => null })
    vi.stubEnv('VITE_CHAT_STREAM_PATH', '/custom/stream')
    expect(resolvePlannerChatStreamPath()).toBe('/custom/stream')
  })
})
