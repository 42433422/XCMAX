// 拆分自 HomeView.vue：类型与纯函数（逻辑逐字迁移，行为不变）。

export interface MarketItem {
  id: number | string
  name: string
  description?: string
  price: number
}

export interface ContactFormState {
  name: string
  email: string
  phone: string
  company: string
  message: string
  privacyAgreed: boolean
}

export function truncate(str: string | undefined | null, len: number): string {
  if (!str) return ''
  return str.length > len ? str.slice(0, len) + '...' : str
}
