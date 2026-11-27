export const MODEL_SERVICE_SECTION = 'model-payment'
export const MODEL_PAYMENT_BRIDGE_ID = 'xcagi-model-payment-bridge'
export const MODEL_SERVICE_WALLET = { id: 'open-model-wallet', label: '打开修茈钱包', kind: 'user_action', requires: 'modelPayment' } as const
export const MODEL_SERVICE_PLANS = { id: 'open-model-plans', label: '会员套餐', kind: 'user_action', requires: 'modelPayment' } as const
export const MODEL_PAYMENT_SECTIONS = {
  balance: { id: 'model-payment-balance', label: '账户余额', requires: 'modelPayment' },
  recharge: { id: 'model-payment-recharge', label: '快捷充值（跳转修茈钱包）', requires: 'modelPayment' },
  membership: { id: 'model-payment-membership', label: MODEL_SERVICE_PLANS.label, requires: 'modelPayment' },
  catalog: { id: 'model-payment-catalog', label: '模型目录与价格', requires: 'modelPayment' },
} as const
export const MODEL_SERVICE_BILLING = {
  id: 'model-service-billing', labelKey: 'settings.modelServiceBilling',
  children: [MODEL_SERVICE_WALLET, MODEL_SERVICE_PLANS, ...Object.values(MODEL_PAYMENT_SECTIONS)],
}
export const MODEL_SERVICE_NAVIGATION = { id: MODEL_SERVICE_SECTION, labelKey: 'settings.modelService', children: [MODEL_SERVICE_BILLING] }

export function canShowModelServiceBilling(mods: readonly { id?: string }[], adminConsole: boolean): boolean {
  return adminConsole || mods.some(mod => String(mod.id || '').trim() === MODEL_PAYMENT_BRIDGE_ID)
}
