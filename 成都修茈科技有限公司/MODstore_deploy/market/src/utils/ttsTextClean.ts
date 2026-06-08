import { stripInternalMarkers } from './lightMarkdown'

/** 将聊天/markdown 文本清洗为适合 TTS 朗读的纯文本。 */
export function cleanTextForTts(raw: string, maxLen = 1500): string {
  const stripped = stripInternalMarkers(raw || '').slice(0, maxLen)
  return stripped
    .replace(/```[\s\S]*?```/g, '')
    .replace(/`[^`]+`/g, '')
    .replace(/!\[[^\]]*\]\([^)]*\)/g, '')
    .replace(/\[[^\]]*\]\([^)]*\)/g, (m) => m.replace(/\[([^\]]*)\]\([^)]*\)/, '$1'))
    .replace(/^#{1,6}\s+/gm, '')
    .replace(/^[-*+]\s+/gm, '')
    .replace(/^\d+\.\s+/gm, '')
    .replace(/^>\s?/gm, '')
    .replace(/\*{1,3}([^*]+)\*{1,3}/g, '$1')
    .replace(/_{1,3}([^_]+)_{1,3}/g, '$1')
    .replace(/~~([^~]+)~~/g, '$1')
    .replace(/[\p{Emoji_Presentation}\p{Extended_Pictographic}\u{FE0F}\u{200D}]/gu, '')
    .replace(/[^\p{L}\p{N}\p{P}\p{S}\p{Z}\n]/gu, '')
    .replace(/\n{2,}/g, '\n')
    .replace(/\s+/g, ' ')
    .trim()
}
