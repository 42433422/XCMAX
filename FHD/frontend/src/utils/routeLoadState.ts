import { ref } from 'vue'

/**
 * 路由页面资源（懒加载分包）加载失败的展示状态。
 * 只用于提示和刷新入口，不改变路由守卫、权限或任何业务行为。
 */
export const routeChunkErrorPath = ref('')

const CHUNK_ERROR_PATTERNS = [
  /Failed to fetch dynamically imported module/i,
  /error loading dynamically imported module/i,
  /Importing a module script failed/i,
  /Unable to preload CSS/i,
  /Loading (CSS )?chunk [\w-]+ failed/i,
]

export function isChunkLoadError(error: unknown): boolean {
  const name = String((error as { name?: unknown } | null)?.name || '')
  const message = String((error as { message?: unknown } | null)?.message || error || '')
  return name === 'ChunkLoadError' || CHUNK_ERROR_PATTERNS.some((re) => re.test(message))
}

export function markRouteChunkError(path: unknown): void {
  routeChunkErrorPath.value = String(path || '/') || '/'
}

export function clearRouteChunkError(): void {
  routeChunkErrorPath.value = ''
}

/** 路由无匹配记录且无名称（不是启动前的初始位置 /）时视为“页面不存在”。 */
export function isUnmatchedRoute(
  route: { matched?: readonly unknown[]; fullPath?: string; path?: string; name?: unknown } | null | undefined,
): boolean {
  if (!route) return false
  const path = String(route.fullPath ?? route.path ?? '')
  return (route.matched?.length ?? 0) === 0 && !route.name && path !== '' && path !== '/'
}
