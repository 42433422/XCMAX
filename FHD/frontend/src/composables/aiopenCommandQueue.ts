/** Per-connection ordering and retry deduplication for screen mutations. */
export function createScreenCommandQueue() {
  let tail: Promise<unknown> = Promise.resolve()
  const pending = new Map<string, Promise<Record<string, unknown>>>()
  const completed = new Map<string, Record<string, unknown>>()
  return (id: string, execute: () => Promise<Record<string, unknown>>) => {
    if (!id) return Promise.resolve({ success: false, code: 'COMMAND_ID_REQUIRED' })
    if (completed.has(id)) return Promise.resolve(completed.get(id)!)
    if (pending.has(id)) return pending.get(id)!
    if (pending.size >= 128) return Promise.resolve({ success: false, code: 'SCREEN_QUEUE_FULL' })
    const result = tail.then(execute).catch((error: unknown) => ({
      success: false, message: error instanceof Error ? error.message : String(error),
    })).then((value) => {
      pending.delete(id)
      completed.set(id, value)
      if (completed.size > 128) completed.delete(completed.keys().next().value!)
      return value
    })
    pending.set(id, result)
    tail = result
    return result
  }
}
