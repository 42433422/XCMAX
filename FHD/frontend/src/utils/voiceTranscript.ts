/**
 * 语音转写结果治理：归一化、低信息量判定与重复抑制。
 *
 * 规则取自 FunASR / whisper.cpp 的文本后处理实践：
 *   - 平台流式识别已开启 itn，数字与单位由服务端归一，这里只做展示层清洗；
 *   - 去掉语种占位标签（<chinese>）与零宽字符；
 *   - 全角字母数字转半角，中文与英文之间补空格；
 *   - 连续重复标点收敛，避免字幕抖动。
 */

const PLACEHOLDER_TAG = /<[^<>\s]{1,24}>/g
const ZERO_WIDTH = /[\u200B-\u200D\uFEFF]/g
/** 全角 ASCII（！到 ～）→ 半角，覆盖全角数字/字母/常见符号。 */
const FULLWIDTH_ASCII = /[\uFF01-\uFF5E]/g
const REPEATED_PUNCT = /([，。！？、；：,.!?;:])\1+/g
const CJK_THEN_LATIN = /([\u4e00-\u9fff])([A-Za-z0-9])/g
const LATIN_THEN_CJK = /([A-Za-z0-9])([\u4e00-\u9fff])/g
const COMPACT_NOISE = /[。．.!！?？，,、；;：:…~（）()"'“”‘’\s]/g

function toHalfWidth(text: string): string {
  return text.replace(FULLWIDTH_ASCII, char => String.fromCharCode(char.charCodeAt(0) - 0xfee0))
}

/** 展示/入库前统一清洗；幂等，可重复调用。 */
export function normalizeVoiceTranscript(raw: string): string {
  const cleaned = String(raw || '')
    .replace(PLACEHOLDER_TAG, ' ')
    .replace(ZERO_WIDTH, '')
  return toHalfWidth(cleaned)
    .replace(REPEATED_PUNCT, '$1')
    .replace(/\s+/g, ' ')
    .replace(CJK_THEN_LATIN, '$1 $2')
    .replace(LATIN_THEN_CJK, '$1 $2')
    .trim()
}

/** 是否包含可发送的语义内容（至少一个字母或数字）。 */
export function hasTranscriptContent(text: string): boolean {
  return /[\p{L}\p{N}]/u.test(text)
}

/** 低信息量：空、纯标点、单字噪声。这类结果不发起新一轮。 */
export function isLowInformationTranscript(text: string): boolean {
  const compact = String(text || '').replace(COMPACT_NOISE, '')
  if (!compact) return true
  if (!hasTranscriptContent(compact)) return true
  return compact.length < 2
}

export interface TranscriptMemory {
  text: string
  at: number
}

/**
 * 重复抑制：同一句话在窗口内重复出现（VAD 抖动、回声、ASR 重发）时丢弃后一次。
 * 返回 true 表示应丢弃。
 */
export function isDuplicateTranscript(
  text: string,
  previous: TranscriptMemory | null,
  withinMs: number,
  now = Date.now(),
): boolean {
  if (!previous?.text) return false
  if (now - previous.at > withinMs) return false
  const current = String(text || '').replace(COMPACT_NOISE, '')
  const last = previous.text.replace(COMPACT_NOISE, '')
  return Boolean(current) && current === last
}
