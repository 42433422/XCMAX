/** 推测式 LLM：过滤空泛承接句，避免「嗯，你说」 */

const FILLER_RE =
  /^(嗯+|啊+|呃+|哦+|好的?|好呀|是的?|对+|行|可以|明白|知道了|继续说|你?说|请讲|我在听)[。！？!?…\s]*$/u

export function isVoiceSpeculativeFiller(text: string): boolean {
  const t = text.trim()
  if (!t || t.length < 4) return true
  if (FILLER_RE.test(t)) return true
  if (t.length < 8 && /^[嗯啊呃哦好是对行]+/.test(t)) return true
  return false
}
