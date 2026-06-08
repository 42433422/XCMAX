export function desktopOpsDeepLink(employeeId?: string): string {
  const base = 'xcagi://ops/duty'
  const id = String(employeeId || '').trim()
  if (!id) return base
  return `${base}?employee=${encodeURIComponent(id)}`
}
