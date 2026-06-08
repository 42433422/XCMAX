import type { ActionRisk } from '../../types/agent'

/** 所有支持的动作类型 */
export const AGENT_ACTIONS = {
  NAVIGATE: 'navigate',
  CLICK: 'click',
  FILL: 'fill',
  SELECT: 'select',
  SCROLL: 'scroll',
  READ: 'read',
  PURCHASE: 'purchase',
  RECHARGE: 'recharge',
  SEARCH_EMPLOYEE: 'search_employee',
} as const

export type AgentActionType = (typeof AGENT_ACTIONS)[keyof typeof AGENT_ACTIONS]

export interface NavigateArgs {
  route: string
  params?: Record<string, string>
  query?: Record<string, string>
}

export interface ClickArgs {
  selector?: string
  butlerTarget?: string
  label?: string
}

export interface FillArgs {
  selector?: string
  butlerTarget?: string
  label?: string
  value: string
}

export interface SelectArgs {
  selector?: string
  butlerTarget?: string
  label?: string
  value: string
}

export interface ScrollArgs {
  direction: 'up' | 'down' | 'top' | 'bottom'
  px?: number
}

export interface ReadArgs {
  target?: 'page' | 'selection' | 'dom'
}

export interface PurchaseArgs {
  planId?: string
  planName?: string
}

export interface SearchEmployeeArgs {
  query: string
}

/** 验证 navigate 参数 */
export function validateNavigateArgs(args: unknown): args is NavigateArgs {
  if (!args || typeof args !== 'object') return false
  const a = args as Record<string, unknown>
  return typeof a.route === 'string' && a.route.length > 0
}

/** 路由名称映射（管家友好名 → 路由 name） */
export const ROUTE_NAME_MAP: Record<string, string> = {
  plans: 'plans',
  会员: 'plans',
  plan: 'plans',
  member: 'plans',
  store: 'ai-store',
  market: 'ai-store',
  'ai-store': 'ai-store',
  AI市场: 'ai-store',
  wallet: 'wallet',
  钱包: 'wallet',
  recharge: 'recharge',
  充值: 'recharge',
  account: 'account',
  设置: 'account',
  workbench: 'workbench-shell',
  工作台: 'workbench-shell',
  home: 'workbench-home',
  首页: 'workbench-home',
  'customer-service': 'customer-service',
  客服: 'customer-service',
  orders: 'orders',
  订单: 'orders',
  templates: 'templates',
  模板: 'templates',
  'wallet-purchased': 'wallet-purchased',
  已购: 'wallet-purchased',
  dev: 'developer-portal',
  developer: 'developer-portal',
  开发者: 'developer-portal',
  notifications: 'notifications',
  通知: 'notifications',
  catalog: 'catalog-detail',
  about: 'about',
  register: 'register',
  注册: 'register',
}

/** 根据 risk 返回动作的默认风险级别 */
export const ACTION_RISKS: Record<AgentActionType, ActionRisk> = {
  [AGENT_ACTIONS.NAVIGATE]: 'low',
  [AGENT_ACTIONS.READ]: 'low',
  [AGENT_ACTIONS.SCROLL]: 'low',
  [AGENT_ACTIONS.CLICK]: 'medium',
  [AGENT_ACTIONS.FILL]: 'medium',
  [AGENT_ACTIONS.SELECT]: 'medium',
  [AGENT_ACTIONS.SEARCH_EMPLOYEE]: 'low',
  [AGENT_ACTIONS.PURCHASE]: 'high',
  [AGENT_ACTIONS.RECHARGE]: 'high',
}
