/** Prefer the server's last conversation. An empty server id keeps the local one. */

export function chooseActiveConversationId(current: string, server: string): string {
  const remote = String(server || '').trim()
  if (remote) return remote
  return String(current || '').trim()
}
