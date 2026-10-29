import { getCurrentScope, onScopeDispose } from 'vue'

/** One request at a time; unchanged snapshots/errors back off, foregrounding refreshes now. */
export function useVisiblePolling(read: () => Promise<boolean>, interval = 2500, maxInterval = 30_000) {
  let timer: ReturnType<typeof setTimeout> | undefined
  let running = false
  let busy = false
  let resume = false
  let generation = 0
  let delay = interval
  const visible = () => typeof document === 'undefined' || document.visibilityState !== 'hidden'
  function clear() { if (timer !== undefined) clearTimeout(timer); timer = undefined }
  function schedule(ms: number) {
    clear()
    if (running && visible()) timer = setTimeout(() => { timer = undefined; void tick() }, ms)
  }
  async function tick() {
    if (!running || !visible()) return
    if (busy) { resume = true; return }
    busy = true
    const current = generation
    let changed = false
    try { changed = await read() } catch { /* Keep the existing data and back off. */ }
    finally {
      busy = false
      if (running) {
        if (resume || current !== generation) { resume = false; delay = interval; schedule(0) }
        else { delay = changed ? interval : Math.min(maxInterval, delay * 2); schedule(delay) }
      }
    }
  }
  function visibilityChanged() {
    clear()
    if (!visible()) return
    delay = interval
    if (busy) resume = true
    else void tick()
  }
  function stop() {
    running = false
    generation++
    resume = false
    clear()
    if (typeof document !== 'undefined') document.removeEventListener('visibilitychange', visibilityChanged)
  }
  function start() {
    stop()
    running = true
    delay = interval
    if (typeof document !== 'undefined') document.addEventListener('visibilitychange', visibilityChanged)
    schedule(interval)
  }
  if (getCurrentScope()) onScopeDispose(stop)
  return { start, stop }
}

/** Full snapshots remain supported; unchanged rows/arrays keep their reactive identity. */
export function reconcileImSnapshot<T extends { id: number }>(current: T[], incoming: T[]): { items: T[]; changed: boolean } {
  const byId = new Map(current.map((item) => [item.id, item]))
  const items = incoming.map((next) => {
    const previous = byId.get(next.id)
    return previous && Object.keys(previous).length === Object.keys(next).length &&
      Object.keys(next).every((key) => previous[key as keyof T] === next[key as keyof T]) ? previous : next
  })
  const changed = items.length !== current.length || items.some((item, index) => item !== current[index])
  return { items: changed ? items : current, changed }
}
