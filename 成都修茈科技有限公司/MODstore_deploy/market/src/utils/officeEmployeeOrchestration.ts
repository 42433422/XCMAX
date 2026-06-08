/**
 * 公开市场 10 个办公员工（读+写）在工作台「聊/做/说」的路由与意图分类。
 * 读取扩展名映射复用 tabularReadEmployees；生成类走 JSON 中介（与 modstore_server runtime 对齐）。
 */
import { OFFICE_EMPLOYEE_PKG_IDS } from '../constants/officeEmployeePack'
import { resolveReadEmployeeForExtension } from './tabularReadEmployees'

export type OfficeFormat = 'word' | 'excel' | 'csv' | 'pdf' | 'ppt'

export type OfficeTaskKind = 'read' | 'generate' | 'analyze' | 'none'

const GENERATE_EMPLOYEE_BY_FORMAT: Record<OfficeFormat, string> = {
  word: 'word-generate-employee',
  excel: 'excel-generate-employee',
  csv: 'csv-generate-employee',
  pdf: 'pdf-generate-employee',
  ppt: 'ppt-generate-employee',
}

const READ_EMPLOYEE_BY_FORMAT: Record<OfficeFormat, string> = {
  word: 'word-full-read-employee',
  excel: 'excel-full-read-employee',
  csv: 'csv-full-read-employee',
  pdf: 'pdf-full-read-employee',
  ppt: 'ppt-full-read-employee',
}

const EXT_TO_FORMAT: Record<string, OfficeFormat> = {
  docx: 'word',
  doc: 'word',
  docm: 'word',
  dotx: 'word',
  dotm: 'word',
  rtf: 'word',
  wps: 'word',
  xlsx: 'excel',
  xlsm: 'excel',
  xls: 'excel',
  csv: 'csv',
  pdf: 'pdf',
  pptx: 'ppt',
  ppt: 'ppt',
}

/** 勿单独匹配 pptx/docx/xlsx，避免「@附件1 xxx.pptx」误判为生成意图 */
const GENERATE_KEYWORDS =
  /生成|导出|写入|输出|制作|创建|写一份|写个|做一份|起草|撰写|word文档|word文件|pdf文件|render|generate|export/i
const GENERATE_OFFICE_EXT_PHRASE =
  /(?:生成|导出|制作|创建|输出|写入).{0,24}(?:pptx?|docx?|xlsx?|pdf|csv)|(?:pptx?|docx?|xlsx?|pdf|csv).{0,24}(?:生成|导出|制作|创建)/i
const GENERATE_EXCLUDE = /全量提取|仅提取|只提取|仅读取|只读|extract only|read only/i
const ANALYZE_KEYWORDS = /总结|分析|解读|要点|洞察|概括|归纳|对比|审查|review|summarize|analyze/i
/** 无「生成」字样但明显要产出 Office 文稿（合同/模板等），避免只走 LLM 口头「稍等」 */
const DOCUMENT_CREATE_NOUN = /合同|协议|模板|证明|通知书|函|简历|清单|报表/
const DOCUMENT_CREATE_EXCLUDE =
  /什么意思|是什么|解释|帮我看|帮我读|审查|风险|条款.*[吗？?]|有没有生成|是否已生成|生成了吗/i

export function officeFormatFromExtension(ext: string): OfficeFormat | null {
  const e = String(ext || '')
    .trim()
    .toLowerCase()
    .replace(/^\./, '')
  return EXT_TO_FORMAT[e] || null
}

export function officeFormatFromFileName(name: string): OfficeFormat | null {
  const parts = String(name || '').split('.')
  if (parts.length < 2) return null
  return officeFormatFromExtension(parts.pop() || '')
}

/** 去掉附件占位、平台附注与文件名，避免 .pptx 等扩展名误触「生成」路由 */
export function normalizeOfficeIntentText(userText: string): string {
  let t = String(userText || '').trim()
  t = t.replace(/\n?\[附件顺序：[^\]]+\]/g, '').trim()
  t = t.replace(/@附件\d+\s*/g, '').trim()
  t = t.replace(/[^\s]+\.(?:pptx?|docx?|xlsx?|xlsm?|xls|csv|pdf)\b/gi, ' ').replace(/\s+/g, ' ').trim()
  return t
}

const OFFICE_INTENT_TRIVIAL = /^(?:完成|好了|ok|okay|继续|可以了|行了|谢谢|thanks?)[\s!！。.，,]*$/i

/** 已附 Office 文件且用户要改版、动效或完成作业类需求 → 读取后生成员 */
const ENHANCE_ATTACHED_KEYWORDS =
  /动画|跑马灯|特效|过渡|补全|完善|改好|做成|做完|完成作业|作业.*(?:加|做|改|完成)|(?:加|做|改|完成).*作业|美化|润色|排版|填充|补齐|更新.*(?:pptx?|幻灯片)|(?:pptx?|幻灯片).*(?:改|加|做)|帮我做|帮我完成|将.{0,12}制作|制作.{0,12}动画|带动画|花卉|播放按钮|均匀排列|横向|纵向|循环播放/i

/** 用户反馈「没有文件/下载不了」→ 应补跑生成员 */
const MISSING_DELIVERABLE_COMPLAINT =
  /还是没有|仍然没有|还是没|没有(?:可)?下载|下载不了|下不了|没生成|没有文件|没有pptx|没有幻灯片|文件呢|产出呢/i

/** 用户明确要操作说明而非产出文件 */
const GUIDE_ONLY_INTENT = /指南|操作步骤|教我怎么做|怎么操作|要.*指南|还是.*指南|操作说明/i

export function resolveGenerateEmployeeForFormat(fmt: OfficeFormat): string {
  return GENERATE_EMPLOYEE_BY_FORMAT[fmt]
}

export function resolveReadEmployeeForFormat(fmt: OfficeFormat): string {
  return READ_EMPLOYEE_BY_FORMAT[fmt]
}

function resolveGenerateFormatFromText(t: string): OfficeFormat {
  const bl = t.toLowerCase()
  if (/ppt|幻灯片|演示/.test(bl)) return 'ppt'
  if (/excel|表格|xlsx|xls/.test(bl)) return 'excel'
  if (/\bcsv\b/.test(bl)) return 'csv'
  if (/\bpdf\b/.test(bl)) return 'pdf'
  if (/word|docx|doc|文档/.test(bl)) return 'word'
  return 'word'
}

export function detectOfficeGenerateIntent(userText: string): { format: OfficeFormat } | null {
  const t = normalizeOfficeIntentText(userText)
  if (!t || GENERATE_EXCLUDE.test(t) || DOCUMENT_CREATE_EXCLUDE.test(t)) return null
  if (GENERATE_KEYWORDS.test(t) || GENERATE_OFFICE_EXT_PHRASE.test(t)) {
    return { format: resolveGenerateFormatFromText(t) }
  }
  // 「销售合同」「通用 Word 模板」等未显式说「生成」也应走生成员，避免 LLM 空口「稍等」
  if (!detectOfficeAnalyzeIntent(t) && DOCUMENT_CREATE_NOUN.test(t)) {
    return { format: resolveGenerateFormatFromText(t) }
  }
  return null
}

export function detectOfficeAnalyzeIntent(userText: string): boolean {
  return ANALYZE_KEYWORDS.test(normalizeOfficeIntentText(userText))
}

/** PPT 生成时优先用用户上传的源幻灯片作模板（保留图片与版式）。 */
export function pickPptTemplateFromSources(
  sources: Array<{ name: string; file?: File | null }>,
): File | null {
  const row = sources.find((s) => /\.pptx?$/i.test(String(s.name || '')) && s.file instanceof File)
  return row?.file ?? null
}

/** 用户已上传 Office 附件且意图为编辑/动效/完成作业（非纯「总结/解读」）。 */
export function detectOfficeEnhanceAttachedIntent(
  userText: string,
  attachmentNames: string[] = [],
): boolean {
  const t = normalizeOfficeIntentText(userText)
  if (!t || GENERATE_EXCLUDE.test(t)) return false
  const hasOffice = attachmentNames.some((n) => officeFormatFromFileName(n) != null)
  if (!hasOffice) return false
  if (ENHANCE_ATTACHED_KEYWORDS.test(t)) return true
  const namesBlob = attachmentNames.join(' ')
  if (/完成|做完|做好/.test(t) && /作业|练习|课堂|幻灯片/i.test(`${t} ${namesBlob}`)) return true
  return false
}

/** 用户要「做出一份」Office 文稿（如销售合同），但未写「生成/导出」等关键词。 */
export function detectOfficeDocumentCreateIntent(userText: string): boolean {
  const t = normalizeOfficeIntentText(userText)
  if (!t || GENERATE_EXCLUDE.test(t) || DOCUMENT_CREATE_EXCLUDE.test(t)) return false
  if (detectOfficeAnalyzeIntent(t)) return false
  return DOCUMENT_CREATE_NOUN.test(t)
}

/** 助手在纯对话里口头承诺「正在生成」，但尚未出现下载卡片。 */
export function assistantImpliesPendingFileGeneration(assistantText: string): boolean {
  const s = String(assistantText || '')
  return (
    /正在(?:为你|您)?(?:生成|制作|创建|导出)/i.test(s) ||
    /(?:生成|制作).{0,20}(?:pptx?|幻灯片|PPT|带动画)/i.test(s) ||
    /步骤\s*\d+\s*\/\s*\d+.*生成员工/i.test(s) ||
    /稍等.*?(?:生成|下载|文件)/i.test(s) ||
    /稍后(?:提供|发送|给你).*?(?:文件|docx|文档|pptx)/i.test(s)
  )
}

export type OfficeMessageAttachmentLike = { name?: string }

/** 从近期用户消息收集曾上传的 Office 附件名（发送后附件会从输入区清空）。 */
/** 合并近期用户话术，避免仅发「完成」时丢失上一轮「跑马灯/动画」等意图。 */
export function collectRecentUserIntentText(
  messages: Array<{ role?: string; content?: string }>,
  maxUserTurns = 8,
): string {
  const parts: string[] = []
  let userTurns = 0
  for (let i = messages.length - 1; i >= 0 && userTurns < maxUserTurns; i -= 1) {
    const m = messages[i]
    if (m?.role !== 'user') continue
    userTurns += 1
    const t = String(m.content || '').trim()
    if (t) parts.unshift(t)
  }
  return parts.join('\n')
}

export function detectUserMissingDeliverableComplaint(userText: string): boolean {
  return MISSING_DELIVERABLE_COMPLAINT.test(normalizeOfficeIntentText(userText))
}

export function collectOfficeAttachmentNamesFromMessages(
  messages: Array<{ role?: string; attachments?: OfficeMessageAttachmentLike[] }>,
  maxUserTurns = 12,
): string[] {
  const names: string[] = []
  let userTurns = 0
  for (let i = messages.length - 1; i >= 0 && userTurns < maxUserTurns; i -= 1) {
    const m = messages[i]
    if (m?.role !== 'user') continue
    userTurns += 1
    for (const a of m.attachments || []) {
      const n = String(a?.name || '').trim()
      if (n && officeFormatFromFileName(n)) names.push(n)
    }
  }
  return [...new Set(names)]
}

export function mergeOfficeAttachmentNames(current: string[], fromConversation: string[]): string[] {
  return [...new Set([...current, ...fromConversation].map((n) => String(n || '').trim()).filter(Boolean))]
}

/** LLM 口头承诺生成 + 会话里曾有 Office 附件 → 应补跑生成员。 */
export function shouldRecoverOfficeGenerate(
  userText: string,
  currentAttachmentNames: string[],
  conversationAttachmentNames: string[],
  assistantPromisedFile: boolean,
  conversationUserText = '',
): boolean {
  const effective = mergeOfficeAttachmentNames(currentAttachmentNames, conversationAttachmentNames)
  const merged = conversationUserText ? `${userText}\n${conversationUserText}` : userText
  if (detectUserMissingDeliverableComplaint(userText) && effective.length > 0) {
    return true
  }
  if (
    detectOfficeGenerateIntent(merged) ||
    detectOfficeDocumentCreateIntent(merged) ||
    detectOfficeEnhanceAttachedIntent(merged, effective)
  ) {
    return true
  }
  return Boolean(assistantPromisedFile && effective.length > 0)
}

/** 助手只给了 PowerPoint 手动步骤、未产出可下载 pptx 时，也应补跑生成员。 */
export function assistantGaveManualOfficeStepsOnly(assistantText: string): boolean {
  const s = String(assistantText || '')
  if (!s.trim()) return false
  const manual =
    /手动操作|在\s*PowerPoint|python-pptx|请告知您的偏好|选项\s*1|选项\s*2|幻灯片放映|动画窗格/i.test(s)
  const hasRealCardHint = /见下方文件卡片|已生成.*output\.pptx/i.test(s)
  return manual && !hasRealCardHint
}

export function classifyOfficeTask(
  userText: string,
  attachmentNames: string[],
  opts?: { conversationUserText?: string },
): OfficeTaskKind {
  const conv = String(opts?.conversationUserText || '').trim()
  const mergedForIntent = conv ? `${userText}\n${conv}` : userText
  const intentText = normalizeOfficeIntentText(userText)
  const formats = attachmentNames
    .map((n) => officeFormatFromFileName(n))
    .filter((f): f is OfficeFormat => f != null)
  const gen = detectOfficeGenerateIntent(mergedForIntent)
  const createDoc = detectOfficeDocumentCreateIntent(mergedForIntent)
  const enhanceAttached = detectOfficeEnhanceAttachedIntent(mergedForIntent, attachmentNames)
  const wantsGenerate = Boolean(gen || createDoc || enhanceAttached)
  const guideOnly =
    formats.length && GUIDE_ONLY_INTENT.test(intentText) && !ENHANCE_ATTACHED_KEYWORDS.test(intentText)
  if (formats.length && OFFICE_INTENT_TRIVIAL.test(intentText)) {
    return enhanceAttached ? 'generate' : 'analyze'
  }
  if (guideOnly) return 'analyze'
  if (wantsGenerate && formats.length) return 'generate'
  if (wantsGenerate && !formats.length) return 'generate'
  if (formats.length) {
    if (detectOfficeAnalyzeIntent(mergedForIntent) && !enhanceAttached) return 'analyze'
    if (wantsGenerate) return 'generate'
    return 'analyze'
  }
  if (detectOfficeAnalyzeIntent(mergedForIntent)) return 'analyze'
  return 'none'
}

export function primaryOfficeFormatFromAttachments(names: string[]): OfficeFormat | null {
  for (const n of names) {
    const f = officeFormatFromFileName(n)
    if (f) return f
  }
  return null
}

export function officeGenerateMissingInputMessage(format?: OfficeFormat | null): string {
  const fmt = format || 'word'
  const extHint =
    fmt === 'word'
      ? '.docx / .doc'
      : fmt === 'excel'
        ? '.xlsx / .xls'
        : fmt === 'ppt'
          ? '.pptx'
          : fmt === 'csv'
            ? '.csv'
            : '.pdf'
  return (
    `要生成可下载的 Office 文件，您可以：**直接用文字描述内容**（平台调用「${resolveGenerateEmployeeForFormat(fmt)}」真实写文件），` +
    `或上传源文件（${extHint}）/结构化 JSON，由「${resolveReadEmployeeForFormat(fmt)}」读取后再生成。对话模型不会直接伪造下载链接。`
  )
}

export function officeEmployeeCapabilitySystemHint(): string {
  return [
    '【办公员工包 · 平台能力】',
    '用户在工作台可使用公开市场 10 个办公员工（Excel/CSV/PDF/PPT/Word 各「全量读取」+「生成」）。',
    '当消息中出现「读取员工解析」附件块或助手消息带有可下载产出时：文件已由 direct_python 真实生成，引导用户在输入框上方的「已生成」文件卡片中点击下载（仅 .pptx/.docx/.xlsx/.pdf 等成品，勿把 presentation_full.json、*.vlm.json 等解析中间文件当作「已生成」推荐）；禁止输出 sandbox: / file: 等伪链接，禁止声称「无法生成/无法提供 docx/xlsx 等文件」。',
    '**未进入生成员工步骤前**，不要写「正在为你生成文件」「稍等」等让用户以为下载卡片即将出现的表述；应说明需包含「生成/导出」或点击「生成 Word」，或等待界面出现「步骤 1/N：正在用生成员工…」。',
    '生成员支持：① 纯文本/JSON 从零 compose（PPT 为多页 output.pptx）；② 上传 pptx 作 template 增强（保留图片+OOXML 动画）；③ 读员工 presentation_full v2 后再生成。',
    'PPT 生成成功后必须引导用户下载 output.pptx，勿只给 PowerPoint 手动操作步骤。',
    '若生成失败，说明可能原因（未部署员工包、权限、输入为空），不要编造下载链接。',
    `已注册员工 id：${OFFICE_EMPLOYEE_PKG_IDS.join('、')}。`,
  ].join('\n')
}

export type OfficePlanSessionLike = { phase?: string; intentKey?: string } | null | undefined

export function shouldHandleAsOfficeTask(
  userText: string,
  attachments: Array<{ name?: string; purpose?: string; status?: string; file?: File }>,
  planSession: OfficePlanSessionLike,
): boolean {
  const ps = planSession
  if (ps && ps.phase && ps.phase !== 'done' && ps.intentKey === 'employee') return false
  const readyOffice = attachments.filter(
    (f) =>
      f.purpose === 'employee' &&
      f.status === 'ready' &&
      f.file instanceof File &&
      resolveReadEmployeeForExtension(
        String(f.name || '')
          .split('.')
          .pop() || '',
      ),
  )
  if (readyOffice.length) return true
  const names = attachments.map((f) => String(f.name || '')).filter(Boolean)
  const kind = classifyOfficeTask(userText, names)
  return kind === 'generate' || kind === 'analyze'
}

export const STARTER_REQUIRES_ATTACHMENT = new Set(['总结文档', '分析 Excel'])

export function starterRequiresAttachment(label: string): boolean {
  return STARTER_REQUIRES_ATTACHMENT.has(label)
}
