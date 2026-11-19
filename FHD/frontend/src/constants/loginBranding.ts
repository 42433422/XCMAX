import packageJson from '../../package.json'

/** 主版本号展示，如 8.0.0 → V8 */
export const XCAGI_VERSION_LABEL = `V${String(packageJson.version || '8.0.0').split('.')[0]}`

export function normalizeLoginSku(raw: string | null | undefined): 'enterprise' | 'generic' {
  const sku = raw?.trim().toLowerCase()
  return sku === 'enterprise' || sku === 'personal' ? 'enterprise' : 'generic'
}

export function loginEyebrow(sku: string): string {
  return normalizeLoginSku(sku) === 'enterprise'
    ? `XCAGI 企业版 · ${XCAGI_VERSION_LABEL}`
    : `XCAGI · ${XCAGI_VERSION_LABEL}`
}

export function loginAccountInputPlaceholder(sku: string): string {
  return normalizeLoginSku(sku) === 'enterprise' ? 'XCAGI 账号或邮箱' : '账号'
}

export function loginPasswordInputPlaceholder(): string {
  return '密码'
}

export function marketBaseUrl(): string {
  return String(import.meta.env.VITE_MARKET_BASE || 'https://xiu-ci.com/market').replace(/\/$/, '')
}

export function marketRegisterUrl(source: 'xcagi-desktop' | 'xcagi-mobile' = 'xcagi-desktop'): string {
  return `${marketBaseUrl()}/register?source=${source}`
}

export function marketForgotPasswordUrl(): string {
  return `${marketBaseUrl()}/forgot-password`
}

export function loginHelpDocUrl(): string {
  return String(import.meta.env.VITE_LOGIN_HELP_URL || '')
}

export type LoginHelpSection = {
  title: string
  items: string[]
}

export const LOGIN_HELP_PAGE_TITLE = '登录帮助'

export function loginPageTitle(sku: string): string {
  return `${loginEyebrow(sku)} · 登录`
}

export const LOGIN_HELP_SECTIONS: LoginHelpSection[] = [
  {
    title: '账号或密码错误',
    items: ['核对账号密码；忘记密码时使用下方找回入口', '仍无法登录时，复制本页诊断信息联系管理员'],
  },
  {
    title: '无法连接应用服务',
    items: ['点击“检查连接”，按检测结果重试登录', '桌面用户可退出并重新打开应用；仍失败时复制诊断信息联系管理员'],
  },
  {
    title: '账号同步',
    items: ['登录后会自动同步账号信息', '同步失败时可稍后重新登录'],
  },
  {
    title: '注册与开通',
    items: ['使用登录页的“注册账号”创建 XCAGI 账号', '在修茈市场选择方案并开通后，返回 XCAGI 登录'],
  },
]
