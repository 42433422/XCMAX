import { mergeAsrLiveText } from './mergeAsrLiveText'

export type VoiceTurnMessage = { role: 'user' | 'assistant'; content: string }

/** 去掉末尾空 assistant，便于把连续 ASR 碎片合并到上一条 user。 */
export function trimTrailingEmptyVoiceAssistants(
  messages: VoiceTurnMessage[],
): VoiceTurnMessage[] {
  const out = [...messages]
  while (out.length) {
    const last = out[out.length - 1]
    if (last?.role !== 'assistant' || String(last.content || '').trim()) break
    out.pop()
  }
  return out
}

/** 是否应将新识别文本并入上一条 user（同一句被过早断句）。 */
export function shouldCoalesceVoiceUserTurn(prev: string, incoming: string): boolean {
  const p = prev.trim()
  const n = incoming.trim()
  if (!p || !n || p === n) return false
  if (n.startsWith(p) || p.startsWith(n)) return true

  const merged = mergeAsrLiveText(p, n, true)
  if (merged.length >= p.length + Math.min(3, n.length)) return true
  if (merged.length >= Math.max(p.length, n.length) * 0.9) return true

  // 短碎片多半是半句话，不单独成气泡
  if (p.length <= 36 && n.length <= 64) return true
  return false
}

export function coalesceVoiceUserText(prev: string, incoming: string): string {
  return mergeAsrLiveText(prev.trim(), incoming.trim(), true).trim()
}

/** 写入 user 回合：合并碎片或追加新气泡。 */
/** 展示层：合并历史中连续的 user 碎片气泡 */
export function foldDisplayVoiceMessages(messages: VoiceTurnMessage[]): VoiceTurnMessage[] {
  const out: VoiceTurnMessage[] = []
  for (const m of messages) {
    if (m.role === 'user' && out.length) {
      const last = out[out.length - 1]
      if (last?.role === 'user' && shouldCoalesceVoiceUserTurn(last.content, m.content)) {
        out[out.length - 1] = {
          role: 'user',
          content: coalesceVoiceUserText(last.content, m.content),
        }
        continue
      }
    }
    out.push({ ...m })
  }
  return out
}

export function appendCoalescedVoiceUserTurn(
  messages: VoiceTurnMessage[],
  incoming: string,
): VoiceTurnMessage[] {
  const trimmed = incoming.trim()
  if (!trimmed) return messages

  let msgs = trimTrailingEmptyVoiceAssistants(messages)
  const last = msgs[msgs.length - 1]
  if (last?.role === 'user' && shouldCoalesceVoiceUserTurn(last.content, trimmed)) {
    msgs = [...msgs]
    msgs[msgs.length - 1] = {
      role: 'user',
      content: coalesceVoiceUserText(last.content, trimmed),
    }
    return msgs
  }
  return [...msgs, { role: 'user', content: trimmed }]
}
