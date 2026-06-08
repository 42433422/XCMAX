import type { ActionRisk, ConfirmStrategy, ActionPermission } from '../../types/agent'

export function getRiskConfirmStrategy(risk: ActionRisk): ConfirmStrategy {
  if (risk === 'low') return 'auto'
  if (risk === 'medium') return 'preview'
  return 'explicit'
}

export function buildActionPermission(
  action: string,
  risk: ActionRisk,
  label: string,
  args?: Record<string, unknown>,
): ActionPermission {
  const strategy = getRiskConfirmStrategy(risk)
  let confirmMessage = `即将执行：${label}`
  if (strategy === 'explicit') {
    if (action === 'purchase') {
      const planName = args?.planName || args?.plan_name || '目标套餐'
      confirmMessage = `即将购买「${planName}」，这是付款操作，确认继续吗？`
    } else if (action === 'recharge') {
      const amount = args?.amount ? `¥${args.amount}` : '指定金额'
      confirmMessage = `即将充值 ${amount}，确认继续吗？`
    } else {
      confirmMessage = `即将执行高风险操作「${label}」，请确认后继续。`
    }
  } else if (strategy === 'preview') {
    confirmMessage = `即将执行：${label}。可以取消。`
  }
  return { action, risk, confirmStrategy: strategy, confirmMessage }
}
