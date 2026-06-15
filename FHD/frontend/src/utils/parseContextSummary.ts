/** 将 `已关联上下文：…（共 N）` 解析为 Cursor 式 pill 展示用片段。 */
export type ParsedContextSummary = {
  chips: string[]
  total: number | null
}

export function parseContextSummary(summary: string | undefined | null): ParsedContextSummary {
  const raw = String(summary || '').trim()
  if (!raw) return { chips: [], total: null }

  const matched = raw.match(/^已关联上下文：(.+?)（共\s*(\d+)）$/)
  if (matched) {
    const chips = matched[1]
      .split(/\s*\+\s*/)
      .map((s) => s.trim())
      .filter(Boolean)
    const total = Number(matched[2])
    return { chips, total: Number.isFinite(total) ? total : null }
  }

  const stripped = raw.replace(/^已关联上下文：/, '').trim()
  return { chips: stripped ? [stripped] : [raw], total: null }
}
