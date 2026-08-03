// Tool protocol sometimes reaches the UI HTML-encoded.  Match that transport
// syntax directly instead of repeatedly decoding arbitrary model text: a
// generic second HTML-unescape can turn harmless user-visible entities into
// markup.
const TOOL_TAG_OPEN = '(?:<|&lt;|&amp;lt;)'
const TOOL_TAG_CLOSE = '(?:>|&gt;|&amp;gt;)'
const TOOL_CALL_MARKER_RE = new RegExp(`${TOOL_TAG_OPEN}\\s*\\/?\\s*tool_call\\b`, 'i')
const TOOL_CALL_BLOCK_RE = new RegExp(
  `${TOOL_TAG_OPEN}\\s*tool_call\\b[\\s\\S]*?(?:${TOOL_TAG_OPEN}\\s*\\/\\s*tool_call\\s*${TOOL_TAG_CLOSE}|$)`,
  'gi',
)

/** Model tool syntax is transport data, never user-visible chat content. */
export function stripModelToolProtocol(raw: unknown): string {
  const original = String(raw || '')
  if (!TOOL_CALL_MARKER_RE.test(original)) return original
  return original.replace(TOOL_CALL_BLOCK_RE, '').trim()
}
