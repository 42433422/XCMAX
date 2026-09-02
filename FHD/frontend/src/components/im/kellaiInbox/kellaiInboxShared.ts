/**
 * 客来来收件箱纯函数标签与格式化工具（拆分自 components/im/KellaiCustomerInbox.vue，行为保持一致）。
 */
import type { KellaiConversationMessage } from '@/api/kellaiBinding'
import { isKellaiImagePlaceholder, resolveKellaiMessageImageSrc } from '@/utils/kellaiMessageMedia'

export function avatarText(name: string): string {
  const value = String(name || '').trim()
  return value ? value.slice(0, 1).toUpperCase() : '客'
}

export function channelLabel(channels?: string[]): string {
  if (!channels?.length) return '客户渠道'
  const labels: Record<string, string> = {
    wecom: '企业微信',
    wechat: '微信',
    douyin: '抖音',
    pdd: '拼多多',
    jd: '京东',
    whatsapp: 'WhatsApp',
  }
  return channels.map((channel) => labels[channel] || channel).join('、')
}

export function formatTime(value?: string): string {
  if (!value) return ''
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return value
  return parsed.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function messageImageSrc(message: KellaiConversationMessage): string {
  return resolveKellaiMessageImageSrc(message)
}

export function isImagePlaceholder(content?: string): boolean {
  return isKellaiImagePlaceholder(String(content || ''))
}

export function riskLabel(value: string): string {
  const labels: Record<string, string> = {
    low: '低风险',
    medium: '中风险',
    high: '高风险',
    critical: '关键风险',
  }
  return labels[value] || '待核验风险'
}

export function draftStatusLabel(value: string): string {
  if (value === 'approved_for_manual_send') return '已批准 · 仅手动发送'
  if (value === 'rejected') return '已拒绝'
  return '等待人工批准'
}

export function taskStatusLabel(value: string): string {
  if (value === 'completed') return '已完成'
  if (value === 'failed') return '执行失败'
  if (value === 'cancelled') return '已取消'
  return '待跟进'
}

export function outcomeLabel(value: string): string {
  if (value === 'success') return '有效'
  if (value === 'no_result') return '暂无结果'
  if (value === 'failed') return '失败'
  return '未记录'
}

export function formatRate(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return '—'
  return `${Math.round(value * 100)}%`
}

export function priorityLabel(value: string): string {
  if (value === 'urgent') return '紧急'
  if (value === 'high') return '高优先级'
  return '普通'
}
