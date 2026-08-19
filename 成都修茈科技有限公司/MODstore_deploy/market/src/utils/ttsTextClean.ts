import { stripInternalMarkers } from './lightMarkdown'

/** 去掉不宜朗读的网址、路径、邮箱与装饰符号。 */
function stripUnspeakableRefs(text: string): string {
  return text
    .replace(/https?:\/\/[^\s\u4e00-\u9fff]+/gi, ' ')
    .replace(/\bwww\.[^\s\u4e00-\u9fff]+/gi, ' ')
    .replace(/[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}/gi, ' ')
    // /case-edu.html、/download/releases 等站内路径
    .replace(
      /\/(?:[\w.-]+\/)*[\w.-]+\.(?:html?|php|aspx?|jsp|json|js|css|png|jpe?g|gif|svg|webp|pdf|zip|dmg|exe|blockmap)\b/gi,
      ' ',
    )
    .replace(
      /(?:^|[\s：:，,；;（(【[])\/(?:[\w.-]+\/)+[\w.-]+\/?(?=[\s。．.！!？?，,；;）)】\]]|$)/g,
      ' ',
    )
    .replace(/(?:^|[\s：:，,；;（(【[])\/[a-z0-9_-]+(?=[\s。．.！!？?，,；;）)】\]]|$)/gi, ' ')
    .replace(/[•●▪▸►◆◇■□→←↔⇒⟶⟵⇄⇅｜|]/g, ' ')
}

/** 将聊天/markdown 文本清洗为适合 TTS 朗读的纯文本。 */
export function cleanTextForTts(raw: string, maxLen = 1500): string {
  const stripped = stripInternalMarkers(raw || '').slice(0, maxLen)
  const markdownClean = stripped
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

  return stripUnspeakableRefs(markdownClean)
    // 路径去掉后残留的「标签：」收成句号，避免空读冒号
    .replace(/[：:]\s*(?=[。．.!！?？]|$)/g, '。')
    .replace(/[：:]\s+/g, '，')
    .replace(/[。．.]{2,}/g, '。')
    .replace(/[，,]{2,}/g, '，')
    .replace(/\n{2,}/g, '\n')
    .replace(/\s+/g, ' ')
    .trim()
}
