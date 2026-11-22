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
