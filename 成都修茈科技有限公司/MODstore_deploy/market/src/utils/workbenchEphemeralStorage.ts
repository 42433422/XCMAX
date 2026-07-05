/**
 * Tab-scoped in-memory store for workbench state that must not be written to
 * sessionStorage/localStorage (CodeQL: js/clear-text-storage-of-sensitive-information).
 * Persists across SPA route changes within the same document; cleared on full reload.
 */
const store = new Map<string, string>()

export function setWorkbenchEphemeral(key: string, value: string): void {
  store.set(key, value)
}

export function getWorkbenchEphemeral(key: string): string | null {
  return store.get(key) ?? null
}

export function removeWorkbenchEphemeral(key: string): void {
  store.delete(key)
}

/** Test-only: reset all ephemeral entries. */
export function clearWorkbenchEphemeralStorage(): void {
  store.clear()
}
