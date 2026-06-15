/** Cursor 式聊天气泡展示：剥离泄漏的工具参数 JSON，转为可读 chip。 */

export type ToolInvocationChip = {
  label: string
  detail?: string
}

const ACTION_LABELS: Record<string, string> = {
  read: '读取',
  convert: '转换',
  write: '写入',
  import: '导入',
  analyze: '分析',
  upload: '上传',
}

export function plainTextFromMessageContent(raw: string | undefined | null): string {
  return String(raw || '')
    .replace(/<br\s*\/?>/gi, '\n')
    .replace(/<[^>]*>/g, '')
    .replace(/&nbsp;/gi, ' ')
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/gi, '"')
    .replace(/&#34;/g, '"')
    .replace(/&#39;/g, "'")
    .trim()
}

function isToolInvocationObject(obj: Record<string, unknown>): boolean {
  if (typeof obj.file_path === 'string' || typeof obj.path === 'string' || typeof obj.excel_path === 'string') {
    return typeof obj.action === 'string' || Object.keys(obj).length <= 4
  }
  if (typeof obj.tool_id === 'string' || typeof obj.tool === 'string' || typeof obj.tool_name === 'string') {
    return true
  }
  return false
}

export function tryParseToolInvocationJson(text: string): Record<string, unknown> | null {
  const raw = String(text || '').trim()
  if (!raw.startsWith('{') || !raw.endsWith('}')) return null
  try {
    const parsed = JSON.parse(raw) as unknown
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return null
    const obj = parsed as Record<string, unknown>
    return isToolInvocationObject(obj) ? obj : null
  } catch {
    return null
  }
}

export function formatToolInvocationChip(obj: Record<string, unknown>): ToolInvocationChip {
  const action = String(obj.action || obj.tool_action || '').trim().toLowerCase()
  const fp = String(obj.file_path || obj.path || obj.excel_path || '').trim()
  const fileName = fp.split('/').pop() || fp
  const actionLabel = ACTION_LABELS[action] || action

  if (fileName && actionLabel) return { label: actionLabel, detail: fileName }
  if (fileName) return { label: '文件', detail: fileName }
  const tool = String(obj.tool_id || obj.tool || obj.tool_name || '').trim()
  if (tool && actionLabel) return { label: tool, detail: actionLabel }
  if (tool) return { label: tool }
  return { label: '工具调用' }
}

export function extractToolInvocationChips(text: string | undefined | null): ToolInvocationChip[] {
  const plain = plainTextFromMessageContent(text)
  if (!plain) return []

  const chips: ToolInvocationChip[] = []
  const seen = new Set<string>()

  for (const line of plain.split('\n')) {
    const obj = tryParseToolInvocationJson(line.trim())
    if (!obj) continue
    const chip = formatToolInvocationChip(obj)
    const key = `${chip.label}|${chip.detail || ''}`
    if (seen.has(key)) continue
    seen.add(key)
    chips.push(chip)
  }

  if (!chips.length) {
    const obj = tryParseToolInvocationJson(plain)
    if (obj) chips.push(formatToolInvocationChip(obj))
  }

  return chips
}

/** 从可见正文中移除工具参数 JSON（单行或多行）。 */
export function stripToolInvocationLeaks(src: string): string {
  const input = String(src || '')
  if (!input.trim()) return ''

  const lines = input.split('\n')
  const kept = lines.filter((line) => !tryParseToolInvocationJson(line.trim()))
  let out = kept.join('\n').trim()

  if (!out && tryParseToolInvocationJson(input.trim())) return ''
  if (tryParseToolInvocationJson(out)) return ''

  return out
}

const STREAMING_PLACEHOLDER_RE = /^\.{2,3}$|^…$|^---$/

export function isStreamingPlaceholderBody(raw: string | undefined | null): boolean {
  const plain = plainTextFromMessageContent(raw)
  return STREAMING_PLACEHOLDER_RE.test(plain)
}

export function hasVisibleChatBubbleBody(raw: string | undefined | null): boolean {
  const plain = plainTextFromMessageContent(raw)
  if (isStreamingPlaceholderBody(plain)) return false
  return !!stripPlannerDisplayMarkers(stripToolInvocationLeaks(plain)).trim()
}

const PLANNER_DISPLAY_MARKERS: RegExp[] = [
  /\[正在调用工具:[^\]\n]+\]/g,
  /【正在调用工具:[^】\n]+】/g,
  /\[正在调用工具:[^\]\n]+(?!\])/g,
  /【正在调用工具:[^】\n]+(?!\】)/g,
  /\[工具已返回[^\]\n]*\]/g,
  /【工具已返回[^】\n]*】/g,
  /\[工具未成功[^\]\n]*\]/g,
  /【工具未成功[^】\n]*】/g,
  /\[需要授权:[^\]\n]+\]/g,
  /【需要授权:[^】\n]+】/g,
  /\[请提供令牌:[^\]\n]+\]/g,
  /【请提供令牌:[^】\n]+】/g,
  /(?<![\[\【])正在调用工具:[^\s\]\】\n]{1,64}/g,
  /\[工具已返回[^\]\n]*(?!\])/g,
  /（仍在处理中，已等待 \d+ 秒，请稍候…）/g,
  /（正在将 Excel 导入数据库[^）]*）/g,
  /（正在生成 Word 文档[^）]*）/g,
  /（正在生成 Excel 工作簿[^）]*）/g,
  /（正在生成可下载文件[^）]*）/g,
  /正在连接修茈模型服务…/g,
]

/** 展示/TTS 前剥离 planner 内部方括号标记（与后端 strip_planner_stream_markers 对齐）。 */
export function stripPlannerDisplayMarkers(src: string): string {
  let out = String(src || '')
  for (const pat of PLANNER_DISPLAY_MARKERS) {
    out = out.replace(pat, '\n')
  }
  return out.replace(/\n{3,}/g, '\n\n').trim()
}

/** MessageBody / 流式渲染用的 Markdown 源文本（从气泡 HTML 还原并清洗）。 */
export function aiMarkdownSourceFromContent(raw: string | undefined | null): string {
  const plain = plainTextFromMessageContent(raw)
  return stripPlannerDisplayMarkers(stripToolInvocationLeaks(plain))
}

export function countThinkingStepLines(steps: string | undefined | null): number {
  return String(steps || '')
    .split('\n')
    .map((s) => s.trim())
    .filter(Boolean).length
}
