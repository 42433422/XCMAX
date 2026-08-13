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

  it('falls back to default session id when session id is empty', () => {
    expect(buildChatMessagesKey('', 'taiyangniao-pro', 'tenant:9')).toBe(
      'xcagi_chat_messages_tenant:9:mod:taiyangniao-pro:default',
    )
  })

  it('reads active mod from storage when modId is omitted', () => {
    expect(buildChatMessagesKey('sess-c', undefined, 'tenant:9')).toBe(
      'xcagi_chat_messages_tenant:9:mod:taiyangniao-pro:sess-c',
    )
    expect(buildChatSessionMetaKey('sess-c', undefined, 'tenant:9')).toBe(
      'xcagi_chat_session_meta_tenant:9:mod:taiyangniao-pro:sess-c',
    )
  })

  it('builds a tenant-only key when no mod is active', () => {
    writeActiveExtensionModIdToStorage('', 'tenant:9')
    expect(buildChatMessagesKey('sess-d', undefined, 'tenant:9')).toBe(
      'xcagi_chat_messages_tenant:9:sess-d',
    )
  })

  it('returns null when the key does not start with the prefix', () => {
    expect(
      extractSessionIdForActiveMod(CHAT_MESSAGES_STORAGE_PREFIX, 'other-prefix:abc', 'm', 'tenant:9'),
    ).toBeNull()
  })

  it('extracts session id for a local (unscoped) key without mod', () => {
    expect(
      extractSessionIdForActiveMod(
        CHAT_MESSAGES_STORAGE_PREFIX,
        `${CHAT_MESSAGES_STORAGE_PREFIX}session-local`,
        undefined,
        'local',
      ),
    ).toBe('session-local')
  })

  it('returns null when a mod-prefixed key does not match the active mod', () => {
    writeActiveExtensionModIdToStorage('', 'tenant:9')
    expect(
      extractSessionIdForActiveMod(
        CHAT_MESSAGES_STORAGE_PREFIX,
        `${CHAT_MESSAGES_STORAGE_PREFIX}tenant:9:mod:other-mod:sess-x`,
        undefined,
        'tenant:9',
      ),
    ).toBeNull()
  })

  it('returns null when the scoped session id is empty', () => {
    writeActiveExtensionModIdToStorage('', 'tenant:9')
    expect(
      extractSessionIdForActiveMod(
        CHAT_MESSAGES_STORAGE_PREFIX,
        `${CHAT_MESSAGES_STORAGE_PREFIX}tenant:9:`,
        undefined,
        'tenant:9',
      ),
    ).toBeNull()
  })

  it('resolves the active mod from storage when activeModId is omitted', () => {
    const key = buildChatMessagesKey('sess-e', 'taiyangniao-pro', 'tenant:9')
    expect(
      extractSessionIdForActiveMod(
        CHAT_MESSAGES_STORAGE_PREFIX,
        key,
        undefined,
        'tenant:9',
      ),
    ).toBe('sess-e')
  })

  it('resolves runtime scope when no scope argument is provided', () => {
    writeActiveExtensionModIdToStorage('', 'tenant:9')
    const key = `${CHAT_MESSAGES_STORAGE_PREFIX}tenant:9:sess-noscope`
    expect(
      extractSessionIdForActiveMod(
        CHAT_MESSAGES_STORAGE_PREFIX,
        key,
        undefined,
      ),
    ).toBe('sess-noscope')
  })

  it('returns null for an explicit empty activeModId against a mod key', () => {
    expect(
      extractSessionIdForActiveMod(
        CHAT_MESSAGES_STORAGE_PREFIX,
        `${CHAT_MESSAGES_STORAGE_PREFIX}tenant:9:mod:xyz:sess`,
        '',
        'tenant:9',
      ),
    ).toBeNull()
  })

  it('returns null for an explicit empty activeModId against an empty session', () => {
    expect(
      extractSessionIdForActiveMod(
        CHAT_MESSAGES_STORAGE_PREFIX,
        `${CHAT_MESSAGES_STORAGE_PREFIX}tenant:9:`,
        '',
        'tenant:9',
      ),
    ).toBeNull()
  })

  it('returns null when scoped tenant segment does not match', () => {
    expect(
      extractSessionIdForActiveMod(
        CHAT_MESSAGES_STORAGE_PREFIX,
        `${CHAT_MESSAGES_STORAGE_PREFIX}tenant:8:sess-z`,
        'm',
        'tenant:9',
      ),
    ).toBeNull()
  })
})
