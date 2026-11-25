import { getRuntimeTenantStorageScopeInput } from '@/utils/tenantStorageScopeRuntime'

/** Renderer-only navigation commands. No command can invoke a business write. */
export const WORKSPACE_COMMANDS = [
  { id: 'palette', label: '搜索命令', defaultChord: 'Mod+K' },
  { id: 'chat', label: '打开智能对话', defaultChord: 'Mod+Alt+J' },
  { id: 'new-chat', label: '新建对话', defaultChord: 'Mod+Alt+N' },
  { id: 'new-task', label: '新建任务草稿', defaultChord: 'Mod+Alt+G' },
  { id: 'sessions', label: '切换历史会话', defaultChord: 'Mod+Shift+H' },
  { id: 'tasks', label: '查看任务工作区', defaultChord: 'Mod+Alt+T' },
  { id: 'sidebar', label: '展开或折叠侧栏', defaultChord: 'Mod+Alt+B' },
] as const

export type WorkspaceCommandId = (typeof WORKSPACE_COMMANDS)[number]['id']
export type WorkspaceShortcutMap = Record<WorkspaceCommandId, string>
export type WorkspaceCommandPreferences = {
  shortcuts: WorkspaceShortcutMap
  recent: string[]
  favorites: string[]
  sidebarCollapsed: boolean | null
}
const PREFIX = 'xcagi.desktop.workspace.commands.v1'
const IDS = new Set<string>(WORKSPACE_COMMANDS.map((command) => command.id))
// Cmd+Option+H is Electron's macOS hideOthers role. Keep the same safe choices on both platforms.
const RESERVED_CHORDS = new Set(['Mod+Alt+H', 'Mod+Q', 'Mod+W', 'Mod+R', 'Mod+T', 'Mod+N', 'Mod+P', 'Mod+F', 'Mod+L', 'Mod+Tab', 'Mod+Comma'])
export const WORKSPACE_SHORTCUT_CHOICES = [
  'Mod+K', 'Mod+Shift+K', 'Mod+Alt+K', 'Mod+Alt+J', 'Mod+Alt+N',
  'Mod+Alt+T', 'Mod+Alt+B', 'Mod+Alt+G', 'Mod+Alt+Y', 'Mod+Shift+J',
  'Mod+Shift+G', 'Mod+Shift+H', 'Mod+Shift+Y',
] as const

export function defaultWorkspaceShortcuts(): WorkspaceShortcutMap {
  return Object.fromEntries(WORKSPACE_COMMANDS.map(({ id, defaultChord }) => [id, defaultChord])) as WorkspaceShortcutMap
}

export function validateWorkspaceShortcut(
  bindings: WorkspaceShortcutMap, id: WorkspaceCommandId, chord: string,
): string {
  if (RESERVED_CHORDS.has(chord)) return '该快捷键属于系统或浏览器保留组合'
  if (!WORKSPACE_SHORTCUT_CHOICES.includes(chord as (typeof WORKSPACE_SHORTCUT_CHOICES)[number])) return '不支持此快捷键'
  if (Object.entries(bindings).some(([key, value]) => key !== id && value === chord)) return '该快捷键已分配给其他工作区命令'
  return ''
}

export type ShortcutKeyEvent = Pick<KeyboardEvent,
  'key' | 'ctrlKey' | 'metaKey' | 'shiftKey' | 'altKey' | 'isComposing' | 'repeat' | 'defaultPrevented' | 'keyCode'> & Partial<Pick<KeyboardEvent, 'code' | 'getModifierState'>>

export function workspaceKeyChord(event: ShortcutKeyEvent, isMac: boolean): string {
  if (event.defaultPrevented || event.repeat || event.isComposing || event.keyCode === 229 || event.getModifierState?.('AltGraph')) return ''
  if (isMac ? (!event.metaKey || event.ctrlKey) : (!event.ctrlKey || event.metaKey)) return ''
  // Option can produce a non-ASCII letter or a dead key on macOS. Use the physical
  // letter only for that modifier combination; regular keyboard layouts keep key semantics.
  const letter = /^[a-z]$/i.test(event.key) ? event.key.toUpperCase()
    : isMac && event.altKey && /^Key[A-Z]$/.test(event.code || '') ? event.code!.slice(3) : ''
  if (!letter) return ''
  return ['Mod', ...(event.altKey ? ['Alt'] : []), ...(event.shiftKey ? ['Shift'] : []), letter].join('+')
}

export function workspaceCommandForKey(
  event: ShortcutKeyEvent, shortcuts: WorkspaceShortcutMap, isMac: boolean,
): WorkspaceCommandId | null {
  const chord = workspaceKeyChord(event, isMac)
  if (!chord || RESERVED_CHORDS.has(chord) || !WORKSPACE_SHORTCUT_CHOICES.includes(chord as (typeof WORKSPACE_SHORTCUT_CHOICES)[number])) return null
  const matches = WORKSPACE_COMMANDS.filter((command) => shortcuts[command.id] === chord)
  return matches.length === 1 ? matches[0].id : null
}

/** Do not persist account metadata, task data, or preferences under unauthenticated/shared keys. */
export function workspaceCommandStorageKey(): string {
  const session = getRuntimeTenantStorageScopeInput()
  if (!session || (session.localUserId == null && session.marketUserId == null)) return ''
  const scope = JSON.stringify([
    session.accountKind || '', session.tenantId ?? null, session.marketUserId ?? null,
    session.localUserId ?? null,
  ])
  return `${PREFIX}:${encodeURIComponent(scope)}`
}

export function defaultWorkspaceCommandPreferences(): WorkspaceCommandPreferences {
  return { shortcuts: defaultWorkspaceShortcuts(), recent: [], favorites: [], sidebarCollapsed: null }
}

function normalizedKeys(value: unknown, limit: number): string[] {
  if (!Array.isArray(value)) return []
  return [...new Set(value.filter((key): key is string => typeof key === 'string'
    && key.length > 0 && key.length < 100 && /^[a-zA-Z0-9._:-]+$/.test(key)))].slice(0, limit)
}

export function readWorkspaceCommandPreferences(
  key: string, storage: Pick<Storage, 'getItem'> | null = typeof localStorage !== 'undefined' ? localStorage : null,
): WorkspaceCommandPreferences {
  const defaults = defaultWorkspaceCommandPreferences()
  if (!key || !storage) return defaults
  try {
    const raw = storage.getItem(key)
    if (!raw || raw.length > 8000) return defaults
    const data = JSON.parse(raw) as Record<string, unknown>
    if (!data || typeof data !== 'object' || Array.isArray(data)) return defaults
    const candidates = data.shortcuts && typeof data.shortcuts === 'object' && !Array.isArray(data.shortcuts)
      ? data.shortcuts as Record<string, unknown> : {}
    const requested: Partial<WorkspaceShortcutMap> = {}
    for (const { id } of WORKSPACE_COMMANDS) {
      const chord = candidates[id]
      if (typeof chord === 'string' &&
        WORKSPACE_SHORTCUT_CHOICES.includes(chord as (typeof WORKSPACE_SHORTCUT_CHOICES)[number]) &&
        !RESERVED_CHORDS.has(chord)) requested[id] = chord
    }
    // Validate the final assignment, not each override against still-unmoved defaults.
    // This preserves intentional two-key swaps after a restart.
    let shortcuts: WorkspaceShortcutMap = { ...defaults.shortcuts, ...requested }
    for (const { id } of WORKSPACE_COMMANDS) {
      const chord = shortcuts[id]
      const duplicate = WORKSPACE_COMMANDS.filter((other) => shortcuts[other.id] === chord)
      if (duplicate.length <= 1) continue
      for (const item of duplicate) {
        if (requested[item.id] !== undefined) shortcuts[item.id] = defaults.shortcuts[item.id]
      }
    }
    if (new Set(Object.values(shortcuts)).size !== WORKSPACE_COMMANDS.length) shortcuts = defaults.shortcuts
    return {
      shortcuts,
      recent: normalizedKeys(data.recent, 12),
      favorites: normalizedKeys(data.favorites, 12),
      sidebarCollapsed: typeof data.sidebarCollapsed === 'boolean' ? data.sidebarCollapsed : null,
    }
  } catch { return defaults }
}

export function writeWorkspaceCommandPreferences(
  key: string, value: WorkspaceCommandPreferences,
  storage: Pick<Storage, 'setItem'> | null = typeof localStorage !== 'undefined' ? localStorage : null,
): boolean {
  if (!key || !storage) return false
  try {
    storage.setItem(key, JSON.stringify({
      shortcuts: value.shortcuts,
      recent: normalizedKeys(value.recent, 12),
      favorites: normalizedKeys(value.favorites, 12),
      sidebarCollapsed: value.sidebarCollapsed,
    }))
    return true
  } catch { return false }
}

export function nextRecentNavKeys(keys: string[], selected: string): string[] {
  return normalizedKeys([selected, ...keys.filter((key) => key !== selected)], 12)
}

export function isWorkspaceCommandId(value: string): value is WorkspaceCommandId {
  return IDS.has(value)
}
