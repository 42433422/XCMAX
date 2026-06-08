/**
 * 管理员运维侧栏（与太阳鸟企业 ERP 壳分离）
 */

export const ADMIN_OPERATOR_CORE_KEYS = new Set([
  'xcmax-admin',
  'chat',
  'ai-ecosystem',
  'settings',
  'mod-store',
  'tools',
  'data-sources',
  'other-tools',
  'workflow-employee-space',
  'workflow-visualization',
  'chat-debug',
  'internal-customer-service',
  'crm-opportunity-view',
])

export const ADMIN_OPERATOR_HOME_ROUTE = 'xcmax-admin'

export const ADMIN_OPERATOR_HIDDEN_MOD_IDS = new Set([
  'taiyangniao-pro',
  'sz-qsm-pro',
])

export const ADMIN_OPERATOR_BLOCKED_ROUTE_NAMES = new Set([
  'products',
  'materials',
  'materials-list',
  'traditional-mode',
  'orders',
  'orders-create',
  'shipment-records',
  'customers',
  'print',
  'approval-hub',
  'approval-workspace',
  'approval-flow-management',
  'approval-rules',
  'inventory',
  'kitten-finance',
])
