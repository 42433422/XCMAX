// 考试试跑视图：类型、常量与纯函数（无状态，便于复用与单测）。
import { ApiError } from '../../infrastructure/http/client'

export const DEFAULT_EMPLOYEE_ID = 'word-full-read-employee'

export type EmployeeOption = { id: string; name: string }

export type PipelineStepId = 'word' | 'prepare_json' | 'report' | 'preview'
export type PipelineStepStatus = 'pending' | 'active' | 'done' | 'error' | 'skipped'

export const PIPELINE_WORD_FLOW: { id: PipelineStepId; label: string }[] = [
  { id: 'word', label: '读取 Word 文档' },
  { id: 'prepare_json', label: '准备 document_full.json' },
  { id: 'report', label: '生成 HTML 量化报告' },
  { id: 'preview', label: '加载报告预览' },
]

export const PIPELINE_JSON_FLOW: { id: PipelineStepId; label: string }[] = [
  { id: 'prepare_json', label: '校验 JSON 文档' },
  { id: 'report', label: '生成 HTML 量化报告' },
  { id: 'preview', label: '加载报告预览' },
]

export type ExamRunKind = 'word_chain' | 'json_only'

/** execute-file + LLM 报告生成允许的最长等待（毫秒） */
export const REPORT_EXECUTE_TIMEOUT_MS = 300_000

/** 考试报告：跳过 LLM，用服务端模板秒级出 HTML（避免长时间卡在「生成报告」） */
export const EXAM_REPORT_INPUT = { action: 'convert' as const, skip_llm: true }

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / (1024 * 1024)).toFixed(1)} MB`
}

export function buildWordChainSummary(sourceDoc: string): string {
  const doc = sourceDoc.trim() || 'Word 文档'
  return [
    '**考试流程已完成**',
    `1. **Word 全量读取**：\`${doc}\` → \`document_full.json\``,
    '2. **JSON 量化报告员**：已生成 HTML 量化报告',
    '',
    '右侧为报告预览；完整摘要与下载见「更多」。',
  ].join('\n')
}

export function formatRunError(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.status === 403) {
      return '无权执行该员工包：需购买/订阅、成为作者，或使用管理员账号。'
    }
    if (e.status === 413) return e.message || '文件过大'
    const msg = e.message || `HTTP ${e.status}`
    if (e.status === 400 && /文件类型|不匹配|\.json/i.test(msg)) {
      return `${msg}（生成报告需后端支持 .json 上传；若 Word 读取已成功，请联系管理员重启 modstore API 或稍后重试。）`
    }
    return msg
  }
  return (e as Error)?.message || String(e)
}

export function renderSummaryHtml(text: string): string {
  if (!text) return ''
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/```([\s\S]*?)```/g, '<pre class="exam-inline-pre">$1</pre>')
    .replace(/\n/g, '<br>')
}

export function computePipelineStepViews(
  flow: typeof PIPELINE_WORD_FLOW | typeof PIPELINE_JSON_FLOW,
  statuses: Record<PipelineStepId, PipelineStepStatus>,
) {
  const iconMap: Record<PipelineStepStatus, string> = {
    pending: '○',
    active: '◉',
    done: '✓',
    error: '✕',
    skipped: '—',
  }
  return flow.map((step) => ({
    id: step.id,
    label: step.label,
    status: statuses[step.id] || ('pending' as PipelineStepStatus),
    icon: iconMap[statuses[step.id] || 'pending'],
  }))
}

export function computePipelinePercent(
  flow: typeof PIPELINE_WORD_FLOW | typeof PIPELINE_JSON_FLOW,
  statuses: Record<PipelineStepId, PipelineStepStatus>,
): number {
  if (!flow.length) return 0
  let score = 0
  for (const step of flow) {
    const st = statuses[step.id]
    if (st === 'done') score += 1
    else if (st === 'active') score += 0.45
    else if (st === 'error') score += 0.2
  }
  return Math.min(100, Math.round((score / flow.length) * 100))
}
