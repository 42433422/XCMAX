/** Current-process observation, distinct from the legacy update badge cache. */
type Observation = { type: string; data?: unknown; observedAt: string | null }
let observation: Observation = { type: 'not-observed', observedAt: null }

export function observeUpdate(type: string, data?: unknown): void {
  observation = { type, data, observedAt: new Date().toISOString() }
}

export function getUpdateObservation(): Observation {
  return { ...observation }
}

export function resetUpdateObservation(): void {
  observation = { type: 'not-observed', observedAt: null }
}
