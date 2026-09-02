// 兼容 façade：实现已按职责域拆分至 ./legacy-monolith/，导出面与原单体完全一致。
import { clearAuthTokens } from '../infrastructure/storage/tokenStore'
import { setTokensFromAuthResponse } from './legacy-monolith/shared'
import { authEndpoints } from './legacy-monolith/auth'
import { walletEndpoints } from './legacy-monolith/wallet'
import { catalogEndpoints } from './legacy-monolith/catalog'
import { adminEndpoints } from './legacy-monolith/admin'
import { modEndpoints } from './legacy-monolith/mods'
import { employeeWorkbenchEndpoints } from './legacy-monolith/employeeWorkbench'
import { scriptWorkflowEndpoints } from './legacy-monolith/scriptWorkflows'
import { workflowEndpoints } from './legacy-monolith/workflows'
import { developerEndpoints } from './legacy-monolith/developer'
import { templateEndpoints } from './legacy-monolith/templates'
import { notificationEndpoints } from './legacy-monolith/notifications'
import { employeeEndpoints } from './legacy-monolith/employees'
import { llmEndpoints } from './legacy-monolith/llm'
import { workbenchEndpoints } from './legacy-monolith/workbench'
import { studioAssetEndpoints } from './legacy-monolith/studioAssets'
import { knowledgeEndpoints } from './legacy-monolith/knowledge'
import { openApiEndpoints } from './legacy-monolith/openApi'
import { customerServiceEndpoints } from './legacy-monolith/customerService'
import { butlerEndpoints } from './legacy-monolith/butler'

/** @deprecated Prefer modular exports from `./api/index`; kept for endpoints not yet migrated. */
export const legacyApi = {
  ...authEndpoints,
  ...walletEndpoints,
  ...catalogEndpoints,
  ...adminEndpoints,
  ...modEndpoints,
  ...employeeWorkbenchEndpoints,
  ...scriptWorkflowEndpoints,
  ...workflowEndpoints,
  ...developerEndpoints,
  ...templateEndpoints,
  ...notificationEndpoints,
  ...employeeEndpoints,
  ...llmEndpoints,
  ...workbenchEndpoints,
  ...studioAssetEndpoints,
  ...knowledgeEndpoints,
  ...openApiEndpoints,
  ...customerServiceEndpoints,
  ...butlerEndpoints,
}

export { setTokensFromAuthResponse, clearAuthTokens }
