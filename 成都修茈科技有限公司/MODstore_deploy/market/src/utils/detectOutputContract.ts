export type OutputContract = 'json' | 'code' | null

const JSON_PATTERNS = [
  /\bjson\s*only\b/i,
  /\bonly\s*json\b/i,
  /仅\s*json/i,
  /只\s*输出\s*json/i,
  /只\s*要\s*json/i,
  /纯\s*json/i,
]

const CODE_PATTERNS = [
  /\bcode\s*only\b/i,
  /\bonly\s*code\b/i,
  /仅\s*代码/i,
  /只\s*输出\s*代码/i,
  /只\s*要\s*代码/i,
  /纯\s*代码/i,
]

/** 从用户消息推断「仅 JSON / 仅代码」输出契约（用于 system prompt）。 */
export function detectOutputContract(userText: string): OutputContract {
  const s = String(userText || '').trim()
  if (!s) return null
  for (const re of JSON_PATTERNS) {
    if (re.test(s)) return 'json'
  }
  for (const re of CODE_PATTERNS) {
    if (re.test(s)) return 'code'
  }
  return null
}

export function outputContractSystemRules(contract: OutputContract): string {
  if (contract === 'json') {
    return [
      '【输出契约：JSON only】',
      '用户要求仅输出 JSON：禁止 markdown 代码围栏（```）、禁止前后说明或标题。',
      '只输出一段合法 JSON 文本（对象或数组），不要包裹在其它格式中。',
    ].join('\n')
  }
  if (contract === 'code') {
    return [
      '【输出契约：code only】',
      '用户要求仅输出代码：禁止解释、禁止反问、禁止 markdown 围栏外的任何文字。',
      '直接给出可运行/可用的代码正文；若必须标注语言，用单行注释而非围栏标签行。',
    ].join('\n')
  }
  return ''
}
