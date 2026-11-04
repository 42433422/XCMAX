/** Create opaque identities for one Business Harness turn, task or message. */
export function createBusinessHarnessId(prefix: 'turn' | 'task' | 'message'): string {
  const randomId = globalThis.crypto?.randomUUID?.().replace(/-/g, '')
  const suffix = randomId || `${Date.now().toString(36)}${Math.random().toString(36).slice(2)}`
  return `${prefix}_${suffix}`
}
