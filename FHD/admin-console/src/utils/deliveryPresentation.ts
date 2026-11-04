import type { CustomDeliveryTicket } from '@/api/xcmaxAdmin'

export const stageOptions = [
  { value: 'queued', label: '已受理', next: '核对客户需求与验收标准，再进入生产。' },
  { value: 'production', label: 'AI 生产中', next: '等待本轮运行、产物与质量结果，再交原客户验收。' },
  { value: 'acceptance', label: '待验收', next: '请原客户按验收标准核对结果；未通过时从原单返工。' },
  { value: 'commerce', label: '待商务闭环', next: '核对原报价与付款结果，再按原单继续交付。' },
  { value: 'rework', label: '待返工', next: '核对本轮失败原因，从原单返工后重新验收。' },
  { value: 'delivering', label: '待安装回执', next: '在客户设备安装，并核对安装与业务运行回执。' },
  { value: 'delivered', label: '已交付', next: '核对原单的安装与客户验收回执；问题复现时从原单返工。' },
]

const deliveryTimeline = [
  { key: 'production', label: 'AI 生产', hint: '真实运行与产物', icon: 'fa-cogs' },
  { key: 'acceptance', label: '质量验收', hint: '质量门与客户确认', icon: 'fa-check-square-o' },
  { key: 'delivering', label: '客户安装', hint: '下载并安装', icon: 'fa-download' },
  { key: 'delivered', label: '回执闭环', hint: '安装证据齐全', icon: 'fa-flag-checkered' },
]

export const initialTimelineSteps = [{ key: 'queued', label: '需求受理', hint: '客户资料入单', icon: 'fa-file-text-o' }, ...deliveryTimeline]
export const addonTimelineSteps = [{ key: 'commerce', label: '需求受理', hint: '新增报价与付款', icon: 'fa-file-text' }, ...deliveryTimeline]

export function stageOf(ticket: CustomDeliveryTicket): string {
  return String(ticket.custom_delivery?.stage || '')
}

export function stageLabel(stage: string): string {
  return stageOptions.find((item) => item.value === stage)?.label || '阶段待核实'
}

export const nextStepLabel = (stage: string) => stageOptions.find(item => item.value === stage)?.next || '阶段未识别，请核对原单记录与交付证据。'

export function kindLabel(kind?: string): string {
  const labels: Record<string, string> = { module: '业务模块', employee: 'AI 员工', bundle: '模块 + AI 员工' }
  return labels[String(kind || '')] || '定制交付'
}
