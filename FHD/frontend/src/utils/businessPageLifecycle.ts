/** Latest-only business reads. Cancelled/superseded requests must never publish rows or errors. */
export function createLatestBusinessRead() {
  let active: AbortController | null = null
  function cancel(): void {
    const previous = active
    active = null
    previous?.abort()
  }
  function begin() {
    cancel()
    const controller = new AbortController()
    active = controller
    return {
      signal: controller.signal,
      isCurrent: () => active === controller && !controller.signal.aborted,
      finish: () => { if (active === controller) active = null },
    }
  }
  return { begin, cancel, isPending: () => active !== null }
}

/** Business failures can arrive in a successful HTTP response. Never claim a write succeeded without its receipt. */
export function requireBusinessSuccess<T extends { success: boolean; message?: string }>(result: T, fallback: string): T {
  if (result?.success !== true) throw new Error(result?.message || fallback)
  return result
}
