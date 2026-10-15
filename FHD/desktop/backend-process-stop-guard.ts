const intentionalStops = new WeakSet<object>()

export function markBackendStopRequested(child: object): void {
  intentionalStops.add(child)
}

export function clearBackendStopRequest(child: object): void {
  intentionalStops.delete(child)
}

export function shouldRestartBackendAfterExit(child: object, appQuitting: boolean, migrationStopping: boolean): boolean {
  return !appQuitting && !migrationStopping && !intentionalStops.has(child)
}
