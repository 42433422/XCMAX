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
  progress: number
}

export function buildLevelProfileDict(experience: number | null | undefined): LevelProfileDict {
  const exp = Math.max(Math.floor(Number(experience) || 0), 0)
  let current = LEVEL_THRESHOLDS[0]
  let nextRow: (typeof LEVEL_THRESHOLDS)[number] | null = null

  for (let idx = 0; idx < LEVEL_THRESHOLDS.length; idx++) {
    const row = LEVEL_THRESHOLDS[idx]
    if (exp >= row.minExp) {
      current = row
      nextRow = idx + 1 < LEVEL_THRESHOLDS.length ? LEVEL_THRESHOLDS[idx + 1]! : null
    } else {
      break
    }
  }

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

/**
 * FastAPI market `/api/auth/me` 为扁平对象；Java 等可能为 `{ user: { ... } }`。
 * 统一成与 Pinia 一致的扁平结构，并兼容 `admin` / `is_admin`。
 */
export function normalizeMeResponse(me: unknown): any {
  if (!me || typeof me !== 'object') return me
  const m = me as Record<string, any>
  const inner = m.user
  if (inner && typeof inner === 'object' && m.id === undefined && inner.id !== undefined) {
    const u = inner as Record<string, any>
    return {
      id: u.id,
      username: u.username,
      email: u.email,
      phone: u.phone,
      is_admin: Boolean(u.is_admin ?? u.admin),
      created_at: u.created_at,
      experience: Number(u.experience ?? m.experience ?? 0) || 0,
      level_profile: u.level_profile ?? m.level_profile,
      avatar_url: u.avatar_url ?? m.avatar_url ?? null,
    }
  }
  return m
}

export function isMeAdminPayload(data: unknown): boolean {
  const flat = normalizeMeResponse(data)
  return flat?.is_admin === true
}
