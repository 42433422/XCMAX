const AVATAR_MAP: Record<string, { key: string; src: string }> = {
  'cursor-super-employee': { key: 'cursor', src: '/brand/cursor-app-icon.svg' },
  'codex-super-employee': { key: 'codex', src: '/brand/codex-app-icon.png' },
  'claude-super-employee': { key: 'claude', src: '/brand/claude-app-icon.svg' },
}

export function superEmployeeAvatarKeyForId(id: string): string | undefined {
  return AVATAR_MAP[id]?.key
}

export function superEmployeeAvatarSrcForId(id: string): string | undefined {
  return AVATAR_MAP[id]?.src
}

export function resolveSuperEmployeeAvatarSrc(id: string, customUrl?: string): string | undefined {
  if (customUrl) return customUrl
  return superEmployeeAvatarSrcForId(id)
}
