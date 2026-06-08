import { describe, it, expect, beforeEach } from 'vitest'
import {
  WB_PLATFORM_CHAT_MODE_KEY,
  readPlatformChatModePreference,
  writePlatformChatModePreference,
} from './workbenchPlatformChatMode'

const LEGACY_KEY = 'wb_platform_chat_mode'

describe('workbenchPlatformChatMode', () => {
  beforeEach(() => {
    sessionStorage.clear()
  })

  it('defaults to on when preference is unset', () => {
    expect(readPlatformChatModePreference()).toBe(true)
  })

  it('respects explicit off on v2 key', () => {
    writePlatformChatModePreference(false)
    expect(readPlatformChatModePreference()).toBe(false)
  })

  it('respects explicit on', () => {
    writePlatformChatModePreference(true)
    expect(readPlatformChatModePreference()).toBe(true)
    expect(sessionStorage.getItem(WB_PLATFORM_CHAT_MODE_KEY)).toBe('1')
  })

  it('migrates legacy on to v2', () => {
    sessionStorage.setItem(LEGACY_KEY, '1')
    expect(readPlatformChatModePreference()).toBe(true)
    expect(sessionStorage.getItem(WB_PLATFORM_CHAT_MODE_KEY)).toBe('1')
  })

  it('migrates legacy mistaken off to default on', () => {
    sessionStorage.setItem(LEGACY_KEY, '0')
    expect(readPlatformChatModePreference()).toBe(true)
    expect(sessionStorage.getItem(WB_PLATFORM_CHAT_MODE_KEY)).toBe('1')
  })
})
