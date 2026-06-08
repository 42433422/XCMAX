import { auth } from './auth'
import { wallet, payment, refunds } from './wallet'
import { catalog } from './catalog'
import { admin } from './admin'
import { mods, packages } from './mods'
import { workbenchEmployee } from './workbench-employee'
import { scriptWorkflows, workflow } from './workflow'
import { developer, templates, notifications } from './developer'
import { employees } from './employees'
import { llm } from './llm'
import { workbench, knowledge, openApiConnectors, customerService, butler } from './workbench'

export { setTokensFromAuthResponse } from './shared'
export { clearAuthTokens } from '../infrastructure/storage/tokenStore'
export * from '../application'

export const api = {
  ...auth,
  ...wallet,
  ...payment,
  ...refunds,
  ...catalog,
  ...admin,
  ...mods,
  ...packages,
  ...workbenchEmployee,
  ...scriptWorkflows,
  ...workflow,
  ...developer,
  ...templates,
  ...notifications,
  ...employees,
  ...llm,
  ...workbench,
  ...knowledge,
  ...openApiConnectors,
  ...customerService,
  ...butler,
}
