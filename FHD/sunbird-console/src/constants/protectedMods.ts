export const PROTECTED_CLIENT_MOD_IDS = ['taiyangniao-pro', 'sz-qsm-pro'] as const

export type ProtectedClientModId = (typeof PROTECTED_CLIENT_MOD_IDS)[number]

const SET = new Set<string>(PROTECTED_CLIENT_MOD_IDS)

export function isProtectedClientModId(modId: string): boolean {
  return SET.has(String(modId || '').trim())
}
