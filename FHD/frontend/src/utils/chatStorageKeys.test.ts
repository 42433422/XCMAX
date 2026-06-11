import { describe, it, expect, beforeEach } from 'vitest'
import {
  buildChatMessagesKey,
  buildChatSessionMetaKey,
  extractSessionIdForActiveMod,
  CHAT_MESSAGES_STORAGE_PREFIX,
} from './chatStorageKeys'
import { writeActiveExtensionModIdToStorage } from './xcagiStorageKeys'
import { setTenantStorageScopeCache } from './tenantStorageScope'

describe('chatStorageKeys tenant isolation', () => {
  beforeEach(() => {
    setTenantStorageScopeCache('tenant:9')
    writeActiveExtensionModIdToStorage('taiyangniao-pro', 'tenant:9')
  })

  it('embeds tenant and mod in chat message key', () => {
    expect(buildChatMessagesKey('sess-a', 'taiyangniao-pro', 'tenant:9')).toBe(
      'xcagi_chat_messages_tenant:9:mod:taiyangniao-pro:sess-a',
    )
  })

  it('extractSessionIdForActiveMod ignores other tenant keys', () => {
    const otherKey = `${CHAT_MESSAGES_STORAGE_PREFIX}tenant:8:mod:taiyangniao-pro:sess-b`
    expect(
      extractSessionIdForActiveMod(
        CHAT_MESSAGES_STORAGE_PREFIX,
        otherKey,
        'taiyangniao-pro',
        'tenant:9',
      ),
    ).toBeNull()
    const ownKey = buildChatMessagesKey('sess-b', 'taiyangniao-pro', 'tenant:9')
    expect(
      extractSessionIdForActiveMod(
        CHAT_MESSAGES_STORAGE_PREFIX,
        ownKey,
        'taiyangniao-pro',
        'tenant:9',
      ),
    ).toBe('sess-b')
  })

  it('session meta key follows same tenant segment', () => {
    expect(buildChatSessionMetaKey('x', 'm', 'tenant:3')).toBe(
      'xcagi_chat_session_meta_tenant:3:mod:m:x',
    )
  })
})
