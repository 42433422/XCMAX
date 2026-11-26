import { afterEach, describe, expect, it } from 'vitest'
import { setRuntimeTenantStorageScopeInput } from '@/utils/tenantStorageScopeRuntime'
import {
  defaultWorkspaceShortcuts, defaultWorkspaceCommandPreferences, workspaceCommandForKey,
  workspaceKeyChord, validateWorkspaceShortcut, workspaceCommandStorageKey,
  readWorkspaceCommandPreferences, writeWorkspaceCommandPreferences, nextRecentNavKeys,
  type ShortcutKeyEvent,
} from './workspaceCommandShortcuts'

const key = (v: Partial<ShortcutKeyEvent> = {}): ShortcutKeyEvent => ({
  key: 'k', ctrlKey: false, metaKey: false, altKey: false, shiftKey: false, repeat: false,
  isComposing: false, defaultPrevented: false, keyCode: 75, ...v,
})
const memory = () => {
  const map = new Map<string, string>()
  return { getItem: (k: string) => map.get(k) ?? null, setItem: (k: string, v: string) => { map.set(k, v) } }
}
afterEach(() => setRuntimeTenantStorageScopeInput(null))

describe('desktop workspace keyboard and preference contract', () => {
  it('matches Windows Ctrl and macOS Command without mixing them', () => {
    const defaults = defaultWorkspaceShortcuts()
    expect(workspaceCommandForKey(key({ ctrlKey: true }), defaults, false)).toBe('palette')
    expect(workspaceCommandForKey(key({ metaKey: true }), defaults, true)).toBe('palette')
    expect(workspaceCommandForKey(key({ metaKey: true }), defaults, false)).toBeNull()
    expect(workspaceCommandForKey(key({ ctrlKey: true }), defaults, true)).toBeNull()
    expect(workspaceKeyChord(key({ ctrlKey: true, altKey: true, key: 'n' }), false)).toBe('Mod+Alt+N')
  })
  it('does not steal composing, repeated, cancelled or native keys', () => {
    const d = defaultWorkspaceShortcuts()
    for (const variation of [
      { isComposing: true }, { keyCode: 229 }, { repeat: true },
      { defaultPrevented: true }, { key: 'Enter' }, { metaKey: true },
    ]) expect(workspaceCommandForKey(key({ ctrlKey: true, ...variation }), d, false)).toBeNull()
  })
  it('detects collisions, reserved combinations, and permits safe changes', () => {
    const d = defaultWorkspaceShortcuts()
    expect(validateWorkspaceShortcut(d, 'chat', d.palette)).toContain('已分配')
    expect(validateWorkspaceShortcut(d, 'chat', 'Mod+W')).not.toBe('')
    expect(validateWorkspaceShortcut(d, 'chat', 'Mod+Alt+Y')).toBe('')
  })
  it('reserves the native macOS hide-others chord and migrates old saved bindings', () => {
    const d = defaultWorkspaceShortcuts()
    const legacy = key({ metaKey: true, altKey: true, key: 'h', code: 'KeyH' })
    expect(validateWorkspaceShortcut(d, 'sessions', 'Mod+Alt+H')).toContain('保留')
    expect(workspaceCommandForKey(legacy, { ...d, sessions: 'Mod+Alt+H' }, true)).toBeNull()
    expect(workspaceCommandForKey(key({ metaKey: true, shiftKey: true, key: 'H' }), d, true)).toBe('sessions')
    const m = memory()
    m.setItem('legacy', JSON.stringify({ shortcuts: { sessions: 'Mod+Alt+H' } }))
    expect(readWorkspaceCommandPreferences('legacy', m).shortcuts.sessions).toBe('Mod+Shift+H')
  })
  it('handles macOS Option-produced characters and rejects AltGraph or duplicate dispatch', () => {
    const d = defaultWorkspaceShortcuts()
    expect(workspaceCommandForKey(key({ metaKey: true, altKey: true, key: 'Dead', code: 'KeyN' }), d, true)).toBe('new-chat')
    expect(workspaceCommandForKey(key({ ctrlKey: true, altKey: true, key: 'n', getModifierState: name => name === 'AltGraph' }), d, false)).toBeNull()
    expect(workspaceCommandForKey(key({ ctrlKey: true }), { ...d, chat: d.palette }, false)).toBeNull()
  })
  it('persists per-account preferences, favorites, recents and layout', () => {
    const m = memory(), prefs = defaultWorkspaceCommandPreferences()
    prefs.shortcuts.chat = 'Mod+Alt+Y'
    prefs.recent = ['chat', 'settings']
    prefs.favorites = ['settings']
    prefs.sidebarCollapsed = true
    expect(writeWorkspaceCommandPreferences('account-A', prefs, m)).toBe(true)
    expect(readWorkspaceCommandPreferences('account-A', m)).toEqual(prefs)
    expect(readWorkspaceCommandPreferences('account-B', m)).toEqual(defaultWorkspaceCommandPreferences())
  })
  it('ignores malformed, conflicting or injected stored state', () => {
    const m = memory()
    m.setItem('key', '{invalid')
    expect(readWorkspaceCommandPreferences('key', m)).toEqual(defaultWorkspaceCommandPreferences())
    m.setItem('key', JSON.stringify({
      shortcuts: { chat: 'Mod+K', tasks: 'Mod+Q' },
      recent: ['chat', 'chat', '<img>', 'settings'],
      favorites: ['<svg>', 'orders'], sidebarCollapsed: 'false',
    }))
    const prefs = readWorkspaceCommandPreferences('key', m)
    expect(prefs.shortcuts.chat).toBe(defaultWorkspaceShortcuts().chat)
    expect(prefs.shortcuts.tasks).toBe(defaultWorkspaceShortcuts().tasks)
    expect(prefs.recent).toEqual(['chat', 'settings'])
    expect(prefs.favorites).toEqual(['orders'])
    expect(prefs.sidebarCollapsed).toBeNull()
  })
  it('keeps recent history bounded and blocks shared anonymous persistence', () => {
    expect(nextRecentNavKeys(Array.from({ length: 20 }, (_, i) => `item-${i}`), 'item-5')).toHaveLength(12)
    expect(nextRecentNavKeys(['settings'], '<unsafe>')).toEqual(['settings'])
    setRuntimeTenantStorageScopeInput(null)
    expect(workspaceCommandStorageKey()).toBe('')
    expect(writeWorkspaceCommandPreferences('', defaultWorkspaceCommandPreferences(), memory())).toBe(false)
    setRuntimeTenantStorageScopeInput({ tenantId: 2, marketUserId: 1 })
    const a = workspaceCommandStorageKey()
    setRuntimeTenantStorageScopeInput({ tenantId: 2, marketUserId: 2 })
    expect(workspaceCommandStorageKey()).not.toBe(a)
  })
  it('keeps valid keyboard shortcut swaps after a restart', () => {
    const m = memory(), prefs = defaultWorkspaceCommandPreferences()
    prefs.shortcuts.palette = 'Mod+Alt+J'
    prefs.shortcuts.chat = 'Mod+K'
    expect(writeWorkspaceCommandPreferences('swap', prefs, m)).toBe(true)
    expect(readWorkspaceCommandPreferences('swap', m).shortcuts).toEqual(prefs.shortcuts)
  })

})
