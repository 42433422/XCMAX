/** Create opaque identities for one Business Harness turn or task. */
export function createBusinessHarnessId(prefix: 'turn' | 'task'): string {
  const randomId = globalThis.crypto?.randomUUID?.().replace(/-/g, '')
  const suffix = randomId || `${Date.now().toString(36)}${Math.random().toString(36).slice(2)}`
  return `${prefix}_${suffix}`
}
