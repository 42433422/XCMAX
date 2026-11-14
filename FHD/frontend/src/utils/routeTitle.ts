/** Title follows only the navigation that actually committed. An aborted click must not rename the page. */

export interface RouteTitleSource {
  fullPath: string
  /** vue-router 5 的 RouteMeta 不再带可索引签名，按实际读取的字段收窄。 */
  meta?: object
}

export function committedRouteTitle(
  to: RouteTitleSource,
  failure: unknown,
  currentFullPath: string,
): string | null {
  if (failure) return null
  if (to.fullPath !== currentFullPath) return null
  const rawTitle = (to.meta as { title?: unknown } | undefined)?.title
  const title = typeof rawTitle === 'string' ? rawTitle.trim() : ''
  return title ? `${title} - XCAGI` : 'XCAGI'
}
