/** Collapse only an exact whole-reply duplicate emitted by an SSE done event. */
export function collapseExactDuplicateReply(raw: string): string {
  const text = String(raw || '').trim()
  if (!text) return text
  const half = text.length / 2
  if (Number.isInteger(half) && text.slice(0, half) === text.slice(half)) {
    return text.slice(0, half).trim()
  }
  const spacedDuplicate = text.match(/^([\s\S]+?)\s+\1$/)
  return spacedDuplicate ? spacedDuplicate[1].trim() : text
}
