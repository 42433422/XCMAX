import type { EnterpriseModStack } from '@/constants/enterpriseModStack'
import { buildEnterpriseModStack } from '@/constants/enterpriseModStack'
import {
  fetchIndustryBaseline,
  fetchOnboardingIndustryCatalog,
} from '@/utils/platformShellApi'
import { fetchWorkspacePrefs } from '@/utils/workspacePrefsApi'

let cachedStack: EnterpriseModStack | null = null

export async function resolveEnterpriseModStack(force = false): Promise<EnterpriseModStack> {
  if (cachedStack && !force) return cachedStack

  let industryId = '通用'
  try {
    const prefs = await fetchWorkspacePrefs()
    const fromPrefs = String(prefs.data?.selected_industry_id || '').trim()
    if (fromPrefs) industryId = fromPrefs
  } catch {
    /* 离线 */
  }
  if (industryId === '通用') {
    try {
      const catalog = await fetchOnboardingIndustryCatalog()
      const fromCatalog = String(catalog?.selected_industry_id || '').trim()
      if (fromCatalog) industryId = fromCatalog
    } catch {
      /* 离线 */
    }
  }

  const plan = await fetchIndustryBaseline(industryId, force)
  cachedStack = buildEnterpriseModStack(plan)
  return cachedStack
}

export function invalidateEnterpriseModStackCache(): void {
  cachedStack = null
}
