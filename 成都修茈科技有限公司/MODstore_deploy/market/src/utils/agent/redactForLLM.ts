/**
 * LLM 发送前 PII 脱敏。
 *
 * 对接契约：
 * - 输入：原始文本（serializeVisibleDom 输出的页面文本摘要、user 消息等）
 * - 输出：脱敏后文本——PII 字段被替换为 ``[REDACTED_<类型>]`` 占位符
 * - 设计目标：**defensive default**——前端先做基础脱敏，后端做权威脱敏。
 *   不可替代 server-side PII 防护；这是给 LLM 视觉/文本链路"加一层手套"。
 *
 * 默认脱敏规则（保守起见宁可误杀）：
 * - 邮箱
 * - 中国大陆手机号（1[3-9]xxxxxxxxx）
 * - 18 位身份证号（末位 x 兼容）
 * - 钱包金额（¥xxx.xx、￥xxx）
 * - 银行卡号（13-19 位连续数字，启发式匹配）
 * - Bearer / API Key 风格的 token
 * - JWT（eyJ... 三段 base64url）
 *
 * 不脱敏（避免误伤 UI 文本）：
 * - 路由路径 / 页面标题 / 普通英文
 * - 数字（订单号、版本号、ID 等长度 ≤ 12 的短数字）
 *   实际是否要脱敏由后端按业务规则决定；这里只防"明显"敏感数据
 */

const REDACTION_PATTERNS: Array<{ kind: string; re: RegExp }> = [
  // 邮箱
  { kind: 'EMAIL', re: /[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}/g },
  // 中国大陆手机号
  { kind: 'PHONE_CN', re: /\b1[3-9]\d{9}\b/g },
  // 18 位身份证
  { kind: 'ID_CARD_CN', re: /\b\d{17}[\dXx]\b/g },
  // 钱包金额（人民币符号）
  { kind: 'WALLET_AMOUNT', re: /[¥￥]\s*\d+(?:[.,]\d+)?/g },
  // 银行卡号启发式：13-19 位连续数字（含空格分隔）
  { kind: 'BANK_CARD', re: /\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{3,4}\b/g },
  // JWT：header.payload.signature
  { kind: 'JWT', re: /\beyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+/g },
  // API Key / Bearer：长度 ≥ 32 的连续 base64url/hex 段
  {
    kind: 'API_KEY',
    re: /\b(?:sk-|pk-|Bearer\s+)[A-Za-z0-9_\-]{16,}/g,
  },
]

/** 单条替换执行。私有——通过 redactForLLM 暴露。 */
function _redactOnce(input: string): string {
  let out = input
  for (const { kind, re } of REDACTION_PATTERNS) {
    out = out.replace(re, `[REDACTED_${kind}]`)
  }
  return out
}

/**
 * 同步脱敏入口。不可用正则触发 ReDoS 的模式（所有 re 都是无嵌套量词的简单扫描）。
 *
 * @param text 原始文本
 * @returns 脱敏后文本
 */
export function redactForLLM(text: string): string {
  if (!text) return text
  return _redactOnce(text)
}

/**
 * 测试/调试用：返回本次脱敏命中的种类和数量。
 * 生产代码请用 redactForLLM。
 */
export function inspectRedactions(text: string): Record<string, number> {
  if (!text) return {}
  const counts: Record<string, number> = {}
  for (const { kind, re } of REDACTION_PATTERNS) {
    re.lastIndex = 0
    const matches = text.match(re)
    if (matches && matches.length) counts[kind] = matches.length
  }
  return counts
}
