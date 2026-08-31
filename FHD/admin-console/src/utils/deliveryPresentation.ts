import type { CustomDeliveryTicket } from '@/api/xcmaxAdmin'

export const stageOptions = [
  { value: 'queued', label: '已受理' },
  { value: 'production', label: 'AI 生产中' },
  { value: 'acceptance', label: '待验收' },
  { value: 'commerce', label: '待商务闭环' },
  { value: 'rework', label: '待返工' },
  { value: 'delivering', label: '待安装回执' },
  { value: 'delivered', label: '已交付' },
]

export const initialTimelineSteps = [
  { key: 'queued', label: '需求受理', hint: '客户资料入单', icon: 'fa-file-text-o' },
  { key: 'production', label: 'AI 生产', hint: '真实运行与产物', icon: 'fa-cogs' },
  { key: 'acceptance', label: '质量验收', hint: '质量门与确认', icon: 'fa-check-square-o' },
  { key: 'delivering', label: '客户安装', hint: '下载并安装', icon: 'fa-download' },
  { key: 'delivered', label: '回执闭环', hint: '安装证据齐全', icon: 'fa-flag-checkered' },
]

export const addonTimelineSteps = [
  { key: 'commerce', label: '新增报价', hint: '付款后开始生产', icon: 'fa-file-text' },
  { key: 'production', label: 'AI 生产', hint: '真实运行与产物', icon: 'fa-cogs' },
  { key: 'acceptance', label: '客户验收', hint: '本人确认产物', icon: 'fa-check-square-o' },
  { key: 'delivering', label: '客户安装', hint: '下载并安装', icon: 'fa-download' },
  { key: 'delivered', label: '回执闭环', hint: '安装证据齐全', icon: 'fa-flag-checkered' },
]

export function stageOf(ticket: CustomDeliveryTicket): string {
  return String(ticket.custom_delivery?.stage || 'queued')
}

export function stageLabel(stage: string): string {
  return stageOptions.find((item) => item.value === stage)?.label || stage
}

export function kindLabel(kind?: string): string {
  const labels: Record<string, string> = { module: '业务模块', employee: 'AI 员工', bundle: '模块 + AI 员工' }
  return labels[String(kind || '')] || '定制交付'
}
