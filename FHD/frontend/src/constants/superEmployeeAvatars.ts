/** 超级员工（Codex / Claude / Cursor）头像 key 与静态资源路径。 */
export type SuperEmployeeAvatarKey = 'codex' | 'claude' | 'cursor';

const BRAND_BASE = `${import.meta.env.BASE_URL || '/'}brand/`;

export const SUPER_EMPLOYEE_AVATAR_KEYS = ['codex', 'claude', 'cursor'] as const;

export const SUPER_EMPLOYEE_AVATAR_SRC: Record<SuperEmployeeAvatarKey, string> = {
  codex: `${BRAND_BASE}codex-app-icon.png`,
  claude: `${BRAND_BASE}claude-app-icon.svg`,
  cursor: `${BRAND_BASE}cursor-app-icon.png`,
};

export const SUPER_EMPLOYEE_ID_TO_AVATAR_KEY: Record<string, SuperEmployeeAvatarKey> = {
  'codex-super-employee': 'codex',
  'claude-super-employee': 'claude',
  'cursor-super-employee': 'cursor',
};

export function superEmployeeAvatarKeyForId(
  employeeId: string | null | undefined,
): SuperEmployeeAvatarKey | null {
  const id = String(employeeId || '').trim();
  return SUPER_EMPLOYEE_ID_TO_AVATAR_KEY[id] || null;
}

export function superEmployeeAvatarSrcForKey(
  key: SuperEmployeeAvatarKey | null | undefined,
): string | null {
  if (!key) return null;
  return SUPER_EMPLOYEE_AVATAR_SRC[key] || null;
}

export function superEmployeeAvatarSrcForId(
  employeeId: string | null | undefined,
): string | null {
  return superEmployeeAvatarSrcForKey(superEmployeeAvatarKeyForId(employeeId));
}

export function resolveSuperEmployeeAvatarSrc(
  employeeId: string | null | undefined,
  avatarUrl?: string | null,
): string | null {
  const explicit = String(avatarUrl || '').trim();
  if (explicit) return explicit;
  return superEmployeeAvatarSrcForId(employeeId);
}
