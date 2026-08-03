const TOOL_CALL_MARKER_RE = /<\s*\/?\s*tool_call\b/i
const TOOL_CALL_BLOCK_RE = /<\s*tool_call\b[\s\S]*?(?:<\s*\/\s*tool_call\s*>|$)/gi

function decodeToolMarkup(value: string): string {
  let decoded = value
  for (let index = 0; index < 2; index += 1) {
    decoded = decoded
      .replace(/&amp;/gi, '&')
      .replace(/&lt;/gi, '<')
      .replace(/&gt;/gi, '>')
      .replace(/&quot;/gi, '"')
  }
  return decoded
}

/** Model tool syntax is transport data, never user-visible chat content. */
export function stripModelToolProtocol(raw: unknown): string {
  const original = String(raw || '')
  const decoded = decodeToolMarkup(original)
  if (!TOOL_CALL_MARKER_RE.test(decoded)) return original
  return decoded.replace(TOOL_CALL_BLOCK_RE, '').trim()
}
