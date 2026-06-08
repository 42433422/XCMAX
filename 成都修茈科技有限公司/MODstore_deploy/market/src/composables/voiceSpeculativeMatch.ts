/** partial 预推理与 final 文本是否可合并为同一 turn */
export function speculativeTextsMatch(finalText: string, partialText: string): boolean {
  const f = finalText.trim()
  const p = partialText.trim()
  if (!f || !p) return false
  if (f === p) return true
  if (f.startsWith(p)) return true
  if (p.startsWith(f)) return true
  const minLen = Math.min(f.length, p.length)
  let same = 0
  for (let i = 0; i < minLen; i++) {
    if (f[i] === p[i]) same++
  }
  return same / Math.max(f.length, p.length) >= 0.85
}
