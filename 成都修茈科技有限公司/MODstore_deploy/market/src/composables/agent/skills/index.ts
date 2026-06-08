import { useRouter } from 'vue-router'
import { skillRegistry } from '../../../utils/agent/agentSkillRegistry'
import { readPageSkill } from './readPageSkill'
import { createNavigateSkill } from './navigateSkill'
import { createSearchEmployeeSkill } from './searchEmployeeSkill'
import { createWalletRechargeSkill } from './walletRechargeSkill'
import { createPurchasePlanSkill } from './purchasePlanSkill'
import { askAllHandsSkill } from './skillAllHandsAsk'

let registered = false

/** 注册所有内置 Butler 技能（仅执行一次） */
export function registerBuiltinSkills(router: ReturnType<typeof useRouter>): void {
  if (registered) return
  registered = true

  skillRegistry.register(readPageSkill)
  skillRegistry.register(createNavigateSkill(router))
  skillRegistry.register(createSearchEmployeeSkill(router))
  skillRegistry.register(createWalletRechargeSkill(router))
  skillRegistry.register(createPurchasePlanSkill(router))
  skillRegistry.register(askAllHandsSkill)
}

export { skillRegistry }
