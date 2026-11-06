/** Title follows only the navigation that actually committed. An aborted click must not rename the page. */

export interface RouteTitleSource {
  fullPath: string
  meta?: { title?: unknown }
}

export function committedRouteTitle(
  to: RouteTitleSource,
  failure: unknown,
  currentFullPath: string,
): string | null {
  if (failure) return null
  if (to.fullPath !== currentFullPath) return null
  const title = typeof to.meta?.title === 'string' ? to.meta.title.trim() : ''
  return title ? `${title} - XCAGI` : 'XCAGI'
}
