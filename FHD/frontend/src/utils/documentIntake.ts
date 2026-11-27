/**
 * 文档接入统一规则：格式白名单、大小上限与预检判定。
 *
 * 智能对话附件、办公文件解析、数据对接中心共用这一份规则，避免各处各自
 * 维护扩展名与上限导致同一份文件夹在不同入口得到不同结论。
 */

export type DocumentIntakeIntent = 'context' | 'analysis' | 'template' | 'office'

export type IntakeSkipReason = 'unsupported' | 'temp_file' | 'duplicate' | 'too_large' | 'batch_limit'

export type IntakeVerdict = 'accepted' | 'convert' | 'skipped'

export interface IntakeItem {
  file: File
  name: string
  size: number
  verdict: IntakeVerdict
  reason?: IntakeSkipReason
  detail: string
  /** 旧 XLS 等需要先转换格式才能入库的文件（仍允许进入处理，由现有转换/提示流程接管）。 */
  needsConversion?: boolean
}

export interface IntakeReport {
  intent: DocumentIntakeIntent
  items: IntakeItem[]
  accepted: File[]
  convertible: File[]
  skipped: IntakeItem[]
  total: number
  acceptedBytes: number
  summary: string
  blocked: boolean
}

interface IntakeRule {
  extensions: ReadonlySet<string>
  /** 需要先转换格式才能导入的扩展名。 */
  convertible: ReadonlySet<string>
  /** 是否按「同名同大小」去重（批量建模板时需要，聊天附件不需要）。 */
  dedupe: boolean
  maxFileBytes: number
  maxBatchBytes: number
  maxFiles: number
}

/** 数据对接中心单批上限：200 个文件 / 50 MB。 */
export const BATCH_MAX_FILES = 200
export const BATCH_MAX_BYTES = 50 * 1024 * 1024
/** 智能对话附件上限：50 个文件 / 单个 12 MB / 合计 48 MB。 */
export const CONTEXT_MAX_FILES = 50
export const CONTEXT_MAX_FILE_BYTES = 12 * 1024 * 1024
export const CONTEXT_MAX_BATCH_BYTES = 48 * 1024 * 1024
export const CHAT_WORD_ATTACHMENT_SUFFIX = '.docx'

const RULES: Record<DocumentIntakeIntent, IntakeRule> = {
  context: {
    extensions: new Set(['.png', '.jpg', '.jpeg', '.webp', '.gif', '.pdf', '.log', '.txt']),
    convertible: new Set(),
    dedupe: false,
    maxFileBytes: CONTEXT_MAX_FILE_BYTES,
    maxBatchBytes: CONTEXT_MAX_BATCH_BYTES,
    maxFiles: CONTEXT_MAX_FILES,
  },
  analysis: {
    extensions: new Set(['.xlsx', '.xlsm', '.xls', '.csv']),
    convertible: new Set(),
    dedupe: true,
    maxFileBytes: BATCH_MAX_BYTES,
    maxBatchBytes: BATCH_MAX_BYTES,
    maxFiles: BATCH_MAX_FILES,
  },
  template: {
    extensions: new Set(['.xlsx', '.xls', '.docx']),
    convertible: new Set(['.xls']),
    dedupe: true,
    maxFileBytes: BATCH_MAX_BYTES,
    maxBatchBytes: BATCH_MAX_BYTES,
    // 数量上限交由数据对接中心自身提示（超过 200 个时保留全量并禁用开始处理）。
    maxFiles: 10000,
  },
  office: {
    extensions: new Set(['.xlsx', '.xlsm', '.xls', '.csv', '.docx', '.doc', '.pdf', '.pptx', '.ppt']),
    convertible: new Set(),
    dedupe: false,
    maxFileBytes: BATCH_MAX_BYTES,
    maxBatchBytes: BATCH_MAX_BYTES,
    maxFiles: BATCH_MAX_FILES,
  },
}

export const INTAKE_SKIP_LABELS: Record<IntakeSkipReason, string> = {
  unsupported: '格式不支持',
  temp_file: '临时文件',
  duplicate: '重复文件',
  too_large: '超过大小上限',
  batch_limit: '超出本批数量',
}

export function fileExtension(name: string): string {
  const index = name.lastIndexOf('.')
  return index >= 0 ? name.slice(index).toLowerCase() : ''
}

export const isChatWordAttachment = (name: string): boolean =>
  fileExtension(name) === CHAT_WORD_ATTACHMENT_SUFFIX

/** Office/macOS 生成的锁文件与资源分支，内容无意义。 */
export function isTemporaryDocument(name: string): boolean {
  return name.startsWith('~$') || name.startsWith('._')
}

export function isDocumentIntakeAllowed(name: string, intent: DocumentIntakeIntent): boolean {
  return RULES[intent].extensions.has(fileExtension(name)) && !isTemporaryDocument(name)
}

/** 生成 `<input accept>` 属性，多个通道取并集。 */
export function intakeAcceptAttribute(...intents: DocumentIntakeIntent[]): string {
  const extensions = new Set<string>()
  for (const intent of intents) for (const ext of RULES[intent].extensions) extensions.add(ext)
  return [...extensions].join(',')
}

function formatMiB(bytes: number): string {
  return `${(bytes / (1024 * 1024)).toFixed(bytes < 1024 * 1024 ? 2 : 1)} MB`
}

export function preflightDocuments(files: File[], intent: DocumentIntakeIntent): IntakeReport {
  return buildIntakeReport(intakeItemsFor(files, intent), intent)
}

/** 把两批预检结果合并展示（追加选择时用），判定结果沿用各自原值。 */
export function mergeIntakeReports(previous: IntakeReport | null, next: IntakeReport): IntakeReport {
  if (!previous) return next
  return buildIntakeReport([...previous.items, ...next.items], next.intent)
}

export function intakeItemsFor(files: File[], intent: DocumentIntakeIntent): IntakeItem[] {
  const rule = RULES[intent]
  const items: IntakeItem[] = []
  const seen = new Set<string>()
  let acceptedCount = 0
  let acceptedBytes = 0

  for (const file of files) {
    const name = String(file.name || '')
    const size = Number(file.size) || 0
    const ext = fileExtension(name)
    const base: IntakeItem = { file, name, size, verdict: 'accepted', detail: '' }

    if (isTemporaryDocument(name)) {
      items.push({ ...base, verdict: 'skipped', reason: 'temp_file', detail: 'Excel 打开时生成的锁文件，没有内容' })
      continue
    }
    if (!rule.extensions.has(ext)) {
      items.push({ ...base, verdict: 'skipped', reason: 'unsupported', detail: ext ? `${ext} 不在可导入格式内` : '没有扩展名' })
      continue
    }
    if (size > rule.maxFileBytes) {
      items.push({ ...base, verdict: 'skipped', reason: 'too_large', detail: `单文件上限 ${formatMiB(rule.maxFileBytes)}` })
      continue
    }
    const needsConversion = rule.convertible.has(ext)
    const duplicateKey = `${name.trim().toLowerCase()}::${size}`
    if (rule.dedupe && seen.has(duplicateKey)) {
      items.push({ ...base, verdict: 'skipped', reason: 'duplicate', detail: '与已选文件同名同大小' })
      continue
    }
    if (acceptedCount >= rule.maxFiles) {
      items.push({ ...base, verdict: 'skipped', reason: 'batch_limit', detail: `单批最多 ${rule.maxFiles} 个文件` })
      continue
    }
    if (acceptedBytes + size > rule.maxBatchBytes) {
      items.push({ ...base, verdict: 'skipped', reason: 'too_large', detail: `本批合计上限 ${formatMiB(rule.maxBatchBytes)}` })
      continue
    }
    if (rule.dedupe) seen.add(duplicateKey)
    acceptedCount += 1
    acceptedBytes += size
    items.push({ ...base, needsConversion, detail: needsConversion ? '旧 XLS，需先转换为 XLSX 再导入' : '' })
  }
  return items
}

export function buildIntakeReport(items: IntakeItem[], intent: DocumentIntakeIntent): IntakeReport {
  const accepted = items.filter((item) => item.verdict === 'accepted').map((item) => item.file)
  const convertible = items.filter((item) => item.verdict === 'accepted' && item.needsConversion).map((item) => item.file)
  const skipped = items.filter((item) => item.verdict === 'skipped')
  const acceptedBytes = items
    .filter((item) => item.verdict === 'accepted')
    .reduce((sum, item) => sum + item.size, 0)
  const reasons = new Map<IntakeSkipReason, number>()
  for (const item of skipped) {
    if (!item.reason) continue
    reasons.set(item.reason, (reasons.get(item.reason) || 0) + 1)
  }
  const parts = [`可导入 ${accepted.length} 个（${formatMiB(acceptedBytes)}）`]
  if (convertible.length) parts.push(`需转换 ${convertible.length} 个`)
  if (skipped.length) {
    const detail = [...reasons.entries()].map(([reason, count]) => `${INTAKE_SKIP_LABELS[reason]} ${count}`).join('、')
    parts.push(`跳过 ${skipped.length} 个（${detail}）`)
  }

  return {
    intent,
    items,
    accepted,
    convertible,
    skipped,
    total: items.length,
    acceptedBytes,
    summary: parts.join(' · '),
    blocked: !accepted.length && !convertible.length,
  }
}
