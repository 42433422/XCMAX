/**
 * useKittenAnalyzer 拆分：常量、类型与纯工具函数（无组件状态）。
 */
import type { Ref } from 'vue'


export const MAX_CHAT_MESSAGES = 120
export const KITTEN_SNAPSHOT_CACHE_MS = 90_000
/** Planner + 工具（如 generate_office_document）可能远超过 120s；过短会 Abort 后走 JSON 再次挂死且无超时 */
export const KITTEN_CHAT_TIMEOUT_MS = (() => {
  const raw = String(import.meta.env.VITE_KITTEN_CHAT_TIMEOUT_MS || '').trim()
  const n = raw ? Number.parseInt(raw, 10) : NaN
  const base = Number.isFinite(n) && n > 0 ? n : 300_000
  return Math.min(600_000, Math.max(60_000, base))
})()

export const KITTEN_WELCOME_HTML =
  '你好，我是 <strong>智慧分析</strong>：日常问答、简单推理、文案与表格草稿。需要时可在右侧<strong>设置</strong>里打开业务库摘要或联网；也可上传表格或从输入旁回形针添加文件。<br><br>直接提问即可。'

export const kittenWorkflowSteps = [
  { key: 'ingest', label: '数据接入', desc: '上传或粘贴数据' },
  { key: 'schema', label: '结构识别', desc: '字段与类型预览' },
  { key: 'analyze', label: '洞察分析', desc: '自然语言与快捷意图' },
  { key: 'deliver', label: '报告输出', desc: '结论、图表与导出' },
] as const

export const kittenOrgCards = [
  { key: 'ingest', title: '数据接入层', desc: 'Excel / CSV / JSON 本地解析，首屏预览' },
  { key: 'schema', title: '语义理解层', desc: '自然语言需求与快捷意图（趋势、ROI、预测等）' },
  {
    key: 'analyze',
    title: '分析执行层',
    desc: '调用后端 /api/ai/chat（专业链路），结合会话上下文与多轮追问',
  },
  { key: 'deliver', title: '交付层', desc: '右侧「分析输出」汇总，支持导出与清除' },
] as const

export const kittenQuickActions = [
  { text: '分析销量趋势', label: '销量趋势' },
  { text: '计算渠道ROI', label: '渠道ROI' },
  { text: '预测下月销量', label: '销量预测' },
  { text: '数据质量检查', label: '数据清洗' },
] as const

export interface KittenDatasetSummary {
  name: string
  rows: number
  columns: number
  fieldNames: string[]
  previewText: string
}

export interface KittenChatMessage {
  role: 'user' | 'ai'
  content: string
  time: string
}

export interface KittenAnalysisResult {
  id: number
  title: string
  summary: string
  chart: boolean
  type: string
  kind: string
}

export type KittenChartType = 'bar' | 'line' | 'pie' | 'scatter' | 'area'
export type KittenChartAggregate = 'count' | 'sum' | 'avg' | 'max' | 'min'

export interface KittenChartConfig {
  type: KittenChartType
  xField: string
  yField: string
  groupField: string
  aggregate: KittenChartAggregate
}

export interface KittenChartRecommendation {
  id: string
  label: string
  description: string
  config: KittenChartConfig
}

export function makeKittenUserId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return `kitten_${crypto.randomUUID()}`
  }
  const nonce = Array.from(crypto.getRandomValues(new Uint8Array(12)), (b) => b.toString(16).padStart(2, '0')).join('')
  return `kitten_${nonce}`
}

export function pushBounded<T>(arrRef: Ref<T[]>, item: T, maxSize: number) {
  arrRef.value.push(item)
  const overflow = arrRef.value.length - maxSize
  if (overflow > 0) {
    arrRef.value.splice(0, overflow)
  }
}

export function escapeHtml(s: string) {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
}

export function textToHtml(s: string) {
  return escapeHtml(s).replace(/\n/g, '<br>')
}

/** Word/Excel 为 ZIP，魔数 PK；若误下到 JSON/HTML 则抛错避免存成 .docx */
export async function assertKittenFileBlob(resp: Response, blob: Blob, label: string): Promise<void> {
  const ct = (resp.headers.get('content-type') || '').toLowerCase()
  if (ct.includes('application/json') || ct.includes('text/html')) {
    const t = await blob.text()
    let msg = `${label}：服务器返回了 ${ct || '非文件'} 而非二进制文档`
    try {
      const j = JSON.parse(t) as { message?: string; detail?: string }
      msg = String(j.message || j.detail || msg)
    } catch {
      const clip = t.trim().slice(0, 200)
      if (clip) msg = `${msg}（片段：${clip}）`
    }
    throw new Error(msg)
  }
  const head = new Uint8Array(await blob.slice(0, 4).arrayBuffer())
  if (head.length >= 2 && head[0] === 0x50 && head[1] === 0x4b) {
    return
  }
  if (head.length >= 1 && (head[0] === 0x7b || head[0] === 0x5b)) {
    const t = await blob.text()
    let msg = `${label}：内容像 JSON（常为 API 基址错误或未登录）`
    try {
      const j = JSON.parse(t) as { message?: string }
      if (typeof j.message === 'string') msg = j.message
    } catch {
      /* ignore */
    }
    throw new Error(msg)
  }
}

export function extractChatApiText(data: Record<string, unknown> | null | undefined): string {
  if (!data || typeof data !== 'object') return ''
  if (typeof data.response === 'string' && data.response.trim()) return data.response.trim()
  const inner = data.data as Record<string, unknown> | undefined
  if (inner && typeof inner.text === 'string' && inner.text.trim()) return inner.text.trim()
  return ''
}

export function extractWebSearchHits(body: unknown): Array<{ title: string; url: string; snippet: string }> {
  if (!body || typeof body !== 'object') return []
  const d = body as Record<string, unknown>
  const layer1 = d.data as Record<string, unknown> | undefined
  const raw = layer1?.web_search_results
  if (!Array.isArray(raw)) return []
  return raw.filter(Boolean).map((x) => {
    const o = x as Record<string, unknown>
    return {
      title: String(o.title ?? ''),
      url: String(o.url ?? ''),
      snippet: String(o.snippet ?? ''),
    }
  })
}

export function buildPreviewTextFromData(data: { preview?: unknown[]; columns?: unknown[] }): string {
  const preview = data.preview
  const cols = data.columns
  if (!preview || !preview.length) return ''
  const lines: string[] = []
  for (const row of preview.slice(0, 3)) {
    if (Array.isArray(row)) {
      lines.push(row.map((c) => String(c ?? '')).join('\t'))
    } else if (row && typeof row === 'object') {
      const keys = Array.isArray(cols) && cols.length ? cols.map(String) : Object.keys(row as object)
      lines.push(keys.map((k) => `${k}: ${(row as Record<string, unknown>)[k] ?? ''}`).join(' | '))
    }
  }
  return lines.join('\n')
}

export function formatKittenSnapshotStatsHint(stats: Record<string, unknown> | null | undefined): string {
  if (!stats || typeof stats !== 'object') return ''
  const parts: string[] = []
  if (stats.materials_total != null) parts.push(`原材料 ${stats.materials_total} 条`)
  if (stats.material_inventory_value_estimate != null) {
    parts.push(`原料库存估 ¥${stats.material_inventory_value_estimate}`)
  }
  if (stats.products_total != null) parts.push(`产品 ${stats.products_total} 条`)
  if (stats.product_inventory_value_estimate != null) {
    parts.push(`成品货值估 ¥${stats.product_inventory_value_estimate}`)
  }
  if (stats.shipments_sample_count != null) {
    parts.push(`近期出货样例 ${stats.shipments_sample_count} 条`)
  }
  return parts.length ? `已就绪：${parts.join(' · ')}` : ''
}

export function htmlToPlainText(html: string): string {
  if (!html) return ''
  const normalized = String(html).replace(/<br\s*\/?>/gi, '\n')
  const doc = new DOMParser().parseFromString(normalized, 'text/html')
  return (doc.body.textContent || '').trim()
}

/** 从气泡 HTML / 纯文本 / 内嵌 JSON 中解析小猫文档取件链接（绝对或 /api 相对路径） */
export function extractKittenDocumentPickupUrl(content: string): string | null {
  if (!content) return null
  const decoded = String(content)
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#x27;/g, "'")
    .replace(/&#39;/g, "'")
    .replace(/&amp;/g, '&')
  const absolute = decoded.match(/https?:\/\/[^\s"'<>)\]]+\/api\/ai\/kitten\/document\/pickup\/[^\s"'<>)\]]+/)
  if (absolute) return absolute[0]
  const relative = decoded.match(/\/api\/ai\/kitten\/document\/pickup\/[^\s"'<>)\]]+/)
  if (relative) return relative[0]
  const jm = decoded.match(/"download_url"\s*:\s*"((?:[^"\\]|\\.)*)"/)
  if (jm?.[1]) {
    const u = jm[1].replace(/\\\//g, '/')
    if (u.includes('/api/ai/kitten/document/pickup/')) {
      if (u.startsWith('http')) return u
      if (u.startsWith('/')) return u
    }
  }
  return null
}

export function buildKittenResultSummary(plain: string, max = 220): string {
  const url = extractKittenDocumentPickupUrl(plain)
  if (plain.length <= max) return plain
  if (url) {
    const idx = plain.indexOf(url)
    const before = (idx >= 0 ? plain.slice(0, idx) : plain.replace(url, '')).replace(/\s+/g, ' ').trim()
    const headMax = Math.max(24, max - url.length - 2)
    const head = before.slice(0, headMax).trimEnd()
    const ell = before.length > headMax ? '…' : ''
    return `${head}${ell}\n${url}`
  }
  return `${plain.slice(0, max)}…`
}

export function formatExportTimestamp(date = new Date()): string {
  const pad = (num: number) => String(num).padStart(2, '0')
  return `${date.getFullYear()}${pad(date.getMonth() + 1)}${pad(date.getDate())}_${pad(date.getHours())}${pad(date.getMinutes())}${pad(date.getSeconds())}`
}

export const emptyChartConfig = (): KittenChartConfig => ({
  type: 'bar',
  xField: '',
  yField: '',
  groupField: '',
  aggregate: 'count',
})

export function buildRecommendedCharts(fields: KittenFieldProfile[]): KittenChartRecommendation[] {
  const numericFields = fields.filter((f) => f.type === 'number')
  const categoryFields = fields.filter((f) => f.type === 'category')
  const dateFields = fields.filter((f) => f.type === 'date')
  const textFields = fields.filter((f) => f.type === 'text')
  const dimension = categoryFields[0] || textFields[0]
  const metric = numericFields[0]
  const secondMetric = numericFields[1]
  const recommendations: KittenChartRecommendation[] = []

  if (dimension) {
    recommendations.push({
      id: `category-count-${dimension.name}`,
      label: `${dimension.name} 分布`,
      description: '按分类字段统计记录数',
      config: {
        type: 'bar',
        xField: dimension.name,
        yField: '',
        groupField: '',
        aggregate: 'count',
      },
    })
  }
  if (dimension && metric) {
    recommendations.push({
      id: `category-sum-${dimension.name}-${metric.name}`,
      label: `${metric.name} 分类汇总`,
      description: '按分类字段汇总核心数值',
      config: {
        type: 'bar',
        xField: dimension.name,
        yField: metric.name,
        groupField: '',
        aggregate: 'sum',
      },
    })
  }
  if (dateFields[0] && metric) {
    recommendations.push({
      id: `date-line-${dateFields[0].name}-${metric.name}`,
      label: `${metric.name} 时间趋势`,
      description: '按日期字段观察数值变化',
      config: {
        type: 'line',
        xField: dateFields[0].name,
        yField: metric.name,
        groupField: '',
        aggregate: 'sum',
      },
    })
  }
  if (dimension) {
    recommendations.push({
      id: `pie-${dimension.name}`,
      label: `${dimension.name} 占比`,
      description: '用饼图查看分类占比',
      config: {
        type: 'pie',
        xField: dimension.name,
        yField: metric?.name || '',
        groupField: '',
        aggregate: metric ? 'sum' : 'count',
      },
    })
  }
  if (metric && secondMetric) {
    recommendations.push({
      id: `scatter-${metric.name}-${secondMetric.name}`,
      label: `${metric.name} / ${secondMetric.name} 相关性`,
      description: '用散点图查看两个数值字段关系',
      config: {
        type: 'scatter',
        xField: metric.name,
        yField: secondMetric.name,
        groupField: '',
        aggregate: 'sum',
      },
    })
  }

  return recommendations.slice(0, 5)
}
