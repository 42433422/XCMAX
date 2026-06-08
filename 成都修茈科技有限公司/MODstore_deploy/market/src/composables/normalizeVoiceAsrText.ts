/** 常见 ASR 同音错字纠正（语音工作台） */
export function normalizeVoiceAsrText(text: string): string {
  let t = String(text || '').trim()
  if (!t) return t

  t = t
    .replace(/^个流[失市柿]对$/, '个流式对话')
    .replace(/流失对话/g, '流式对话')
    .replace(/流市对话/g, '流式对话')
    .replace(/流[失市柿](?!式)/g, '流式')
    .replace(/修[茈兹]/g, '修茈')
    .replace(/\s+/g, ' ')
    .trim()

  return t
}
