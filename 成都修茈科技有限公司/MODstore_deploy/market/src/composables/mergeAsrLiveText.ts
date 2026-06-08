/** 合并 ASR 流式 partial，避免短片段覆盖已识别长文本。 */
export function mergeAsrLiveText(prev: string, incoming: string, isFinal = false): string {
  const p = prev.trim()
  const n = incoming.trim()
  if (!n) return p
  if (!p) return n
  if (n === p) return p
  if (isFinal) return n.length >= p.length ? n : p

  if (n.startsWith(p)) return n
  if (p.startsWith(n)) return p

  const maxOverlap = Math.min(p.length, n.length, 48)
  for (let k = maxOverlap; k >= 1; k--) {
    if (p.endsWith(n.slice(0, k))) {
      const suffix = n.slice(k)
      if (suffix && (k >= 3 || n.length >= p.length * 0.55)) {
        return p + suffix
      }
      break
    }
    if (n.startsWith(p.slice(p.length - k))) {
      return p.slice(0, p.length - k) + n
    }
  }

  if (p.includes(n)) return p
  if (n.includes(p)) return n

  // 在线 partial 偶发回退为更短片段：保留更长的已有文本
  if (p.length > n.length + 2) return p
  return n.length > p.length ? n : p
}
