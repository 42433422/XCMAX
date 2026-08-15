/**
 * 与 modstore_server/account_level_service.py 中 LEVEL_THRESHOLDS / build_level_profile 保持一致，
 * 用于 /api/auth/me 未带 level_profile（如 Java 网关）或仅带 experience 时的前端展示。
 */
export const LEVEL_THRESHOLDS: ReadonlyArray<{ level: number; minExp: number; title: string }> = [
  { level: 1, minExp: 0, title: '新手' },
  { level: 2, minExp: 1_000, title: '探索者' },
  { level: 3, minExp: 5_000, title: '创作者' },
  { level: 4, minExp: 20_000, title: '专家' },
  { level: 5, minExp: 50_000, title: '大师' },
  { level: 6, minExp: 100_000, title: '宗师' },
  { level: 7, minExp: 200_000, title: '传奇' },
]

export type LevelProfileDict = {
  level: number
  title: string
  experience: number
  current_level_min_exp: number
  next_level_min_exp: number | null
  /** 当前等级到下一等级的进度，范围 [0, 1]；已封顶时固定为 1。 */
  progress: number
}

export function buildLevelProfileDict(experience: number | null | undefined): LevelProfileDict {
  const exp = Math.max(Math.floor(Number(experience) || 0), 0)
  const idx = LEVEL_THRESHOLDS.findLastIndex((row) => exp >= row.minExp)
  const safeIdx = idx < 0 ? 0 : idx
  const current = LEVEL_THRESHOLDS[safeIdx]
  const nextRow = LEVEL_THRESHOLDS[safeIdx + 1] ?? null

  const currentMin = current.minExp
  const nextMin = nextRow?.minExp ?? null
  let progress = 1
  if (nextMin !== null) {
    const span = Math.max(nextMin - currentMin, 1)
    progress = Math.max(0, Math.min(1, (exp - currentMin) / span))
  }

  return {
    level: current.level,
    title: current.title,
    experience: exp,
    current_level_min_exp: currentMin,
    next_level_min_exp: nextMin,
    progress: Math.round(progress * 10_000) / 10_000,
  }
}

/** 已规范化的 /api/auth/me 响应（扁平结构）。 */
export type NormalizedMe = {
  id?: number | string
  username?: string
  email?: string
  phone?: string
  is_admin: boolean
  created_at?: string
  experience: number
  level_profile?: unknown
  avatar_url?: string | null
  account_state?: string
  next_action?: string
  desktop_access?: boolean
  active_plan_id?: string
}

function normalizeAccessFlag(value: unknown): boolean {
  if (value === true || value === 1) return true
  if (typeof value !== 'string') return false
  return ['1', 'true', 'yes'].includes(value.trim().toLowerCase())
}

/**
 * FastAPI market `/api/auth/me` 为扁平对象；Java 等可能为 `{ user: { ... } }`。
 * 统一成与 Pinia 一致的扁平结构，并兼容 `admin` / `is_admin`。
 * 非对象输入（字符串、数字等）一律返回 null，调用方需做 null 检查。
 */
export function normalizeMeResponse(me: unknown): NormalizedMe | null | undefined {
  if (me === null) return null
  if (me === undefined) return undefined
  if (typeof me !== 'object') return null
  const m = me as Record<string, unknown>
  const inner = m.user
  if (
    inner &&
    typeof inner === 'object' &&
    m.id === undefined &&
    (inner as { id?: unknown }).id !== undefined
  ) {
    const u = inner as Record<string, unknown>
    return {
      id: u.id as number | string | undefined,
      username: u.username as string | undefined,
      email: u.email as string | undefined,
      phone: u.phone as string | undefined,
      is_admin: Boolean(u.is_admin ?? u.admin),
      created_at: u.created_at as string | undefined,
      experience: Number(u.experience ?? m.experience ?? 0) || 0,
      level_profile: u.level_profile ?? m.level_profile,
      avatar_url: (u.avatar_url ?? m.avatar_url ?? null) as string | null | undefined,
      account_state: (u.account_state ?? m.account_state) as string | undefined,
      next_action: (u.next_action ?? m.next_action) as string | undefined,
      desktop_access: normalizeAccessFlag(u.desktop_access ?? m.desktop_access),
      active_plan_id: (u.active_plan_id ?? m.active_plan_id) as string | undefined,
    }
  }
  return m as NormalizedMe
}

export function isMeAdminPayload(data: unknown): boolean {
  const flat = normalizeMeResponse(data)
  return !!flat && typeof flat === 'object' && flat.is_admin === true
}
