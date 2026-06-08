const SENTENCE_END = /[。！？；.!?]\s*|\n+/

export interface SplitOptions {
  minLen?: number
  maxLen?: number
  /** 流式语音模式：逗号/顿号且片段足够长时提前 emit */
  earlyClause?: boolean
  /** earlyClause 模式下片段最短字数 */
  earlyClauseMinLen?: number
  /** 尚无标点切句时，首段达到此字数即强制 emit 一次（加速 TTS 首响） */
  firstChunkLen?: number
}

const CLAUSE_END = /[，、,]\s*/

function extractEarlyClauses(text: string, opts: SplitOptions): string[] {
  if (!opts.earlyClause) return []
  const minClause = opts.earlyClauseMinLen ?? 8
  const t = (text || '').trim()
  if (!t) return []
  const parts = t.split(CLAUSE_END).map((p) => p.trim()).filter(Boolean)
  if (parts.length <= 1) return []
  const endsWithClause = CLAUSE_END.test(t.slice(-2)) || /[，、,]$/.test(t)
  const complete = endsWithClause ? parts : parts.slice(0, -1)
  return complete.filter((p) => p.length >= minClause)
}

function splitLongSegment(text: string, maxLen: number): string[] {
  const t = text.trim()
  if (!t) return []
  if (t.length <= maxLen) return [t]
  const out: string[] = []
  let rest = t
  while (rest.length > maxLen) {
    let cut = maxLen
    const comma = rest.lastIndexOf('，', maxLen)
    const space = rest.lastIndexOf(' ', maxLen)
    if (comma > maxLen * 0.4) cut = comma + 1
    else if (space > maxLen * 0.4) cut = space + 1
    out.push(rest.slice(0, cut).trim())
    rest = rest.slice(cut).trim()
  }
  if (rest) out.push(rest)
  return out
}

function mergeShortSegments(segments: string[], minLen: number): string[] {
  if (!segments.length) return []
  const merged: string[] = []
  let buf = ''
  for (const seg of segments) {
    const s = seg.trim()
    if (!s) continue
    if (!buf) {
      buf = s
      continue
    }
    if (buf.length < minLen) {
      buf = `${buf}${s}`
    } else {
      merged.push(buf)
      buf = s
    }
  }
  if (buf) merged.push(buf)
  return merged
}

/** 去掉已 emit 的前缀/完全重复，返回仍需播报的增量片段。 */
export function subtractEmittedSegments(segments: string[], emittedTexts: string[]): string[] {
  const emitted = emittedTexts.map((e) => e.trim()).filter(Boolean)
  const fresh: string[] = []
  for (const seg of segments) {
    let rest = (seg || '').trim()
    if (!rest) continue
    if (emitted.includes(rest)) continue
    for (const e of [...emitted].sort((a, b) => b.length - a.length)) {
      if (rest.startsWith(e) && rest.length > e.length) {
        rest = rest.slice(e.length).trim()
      } else if (rest === e) {
        rest = ''
        break
      }
    }
    if (!rest || emitted.includes(rest) || fresh.includes(rest)) continue
    fresh.push(rest)
  }
  return fresh
}

/** 从文本中提取已完成的句子（末尾未闭合的片段不包含在内）。 */
export function extractCompleteSentences(text: string, opts?: SplitOptions): string[] {
  const minLen = opts?.minLen ?? 6
  const maxLen = opts?.maxLen ?? 120
  const t = (text || '').trim()
  if (!t) return []

  const sentenceParts = t.split(SENTENCE_END).map((p) => p.trim()).filter(Boolean)
  const endsWithTerminator = SENTENCE_END.test(t.slice(-2)) || /[。！？；.!?]$/.test(t)
  const completeParts = endsWithTerminator ? sentenceParts : sentenceParts.slice(0, -1)

  const earlyParts = extractEarlyClauses(t, opts || {})
  const mergedParts = [...earlyParts]
  for (const p of completeParts) {
    if (!mergedParts.some((m) => p.startsWith(m) || m.startsWith(p))) {
      mergedParts.push(p)
    }
  }
  if (!mergedParts.length) return []

  const expanded: string[] = []
  for (const p of mergedParts) {
    expanded.push(...splitLongSegment(p, maxLen))
  }
  return mergeShortSegments(expanded, minLen)
}

/** 静态全文分句（含末尾剩余片段）。 */
export function splitSentences(text: string, opts?: SplitOptions): string[] {
  const minLen = opts?.minLen ?? 6
  const maxLen = opts?.maxLen ?? 120
  const t = (text || '').trim()
  if (!t) return []

  const parts = t.split(SENTENCE_END).map((p) => p.trim()).filter(Boolean)
  if (!parts.length) return [t]

  const expanded: string[] = []
  for (const p of parts) {
    expanded.push(...splitLongSegment(p, maxLen))
  }
  const merged = mergeShortSegments(expanded, minLen)
  return merged.length ? merged : [t]
}

export interface StreamSplitter {
  feed(soFar: string): string[]
  finish(soFar: string): string[]
  reset(): void
}

/** 增量分句器：配合 LLM 流式输出，首句就绪即返回。 */
export function createStreamSplitter(opts?: SplitOptions): StreamSplitter {
  let emittedTexts: string[] = []
  let firstChunkEmitted = false

  const commitFresh = (parts: string[]): string[] => {
    const fresh = subtractEmittedSegments(parts, emittedTexts)
    if (fresh.length) emittedTexts = [...emittedTexts, ...fresh]
    return fresh
  }

  const extractFirstChunk = (soFar: string): string[] => {
    const minLen = opts?.firstChunkLen ?? 0
    if (!minLen || firstChunkEmitted || emittedTexts.length) return []
    const complete = extractCompleteSentences(soFar, opts)
    if (complete.length) return []
    const t = (soFar || '').trim()
    if (t.length < minLen) return []
    firstChunkEmitted = true
    return [t.slice(0, minLen)]
  }

  return {
    feed(soFar: string): string[] {
      const fromComplete = commitFresh(extractCompleteSentences(soFar, opts))
      if (fromComplete.length) return fromComplete
      return commitFresh(extractFirstChunk(soFar))
    },
    finish(soFar: string): string[] {
      return commitFresh(splitSentences(soFar, opts))
    },
    reset() {
      emittedTexts = []
      firstChunkEmitted = false
    },
  }
}
