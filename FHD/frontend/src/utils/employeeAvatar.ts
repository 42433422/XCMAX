/**
 * 员工头像池：复用移动端 assets/avatars 素材（已压缩为 128px）。
 * 同一员工 id 始终得到同一头像，避免列表刷新时头像跳动。
 */
const modules = import.meta.glob('../assets/avatars/employees/*.png', {
  eager: true,
  query: '?url',
  import: 'default',
}) as Record<string, string>

export const EMPLOYEE_AVATAR_POOL: string[] = Object.keys(modules)
  .sort()
  .map((key) => modules[key])

export function employeeAvatarUrl(seed: string): string {
  if (!EMPLOYEE_AVATAR_POOL.length) return ''
  const text = String(seed || '')
  let hash = 2166136261
  for (let i = 0; i < text.length; i += 1) {
    hash ^= text.charCodeAt(i)
    hash = Math.imul(hash, 16777619)
  }
  return EMPLOYEE_AVATAR_POOL[(hash >>> 0) % EMPLOYEE_AVATAR_POOL.length]
}
