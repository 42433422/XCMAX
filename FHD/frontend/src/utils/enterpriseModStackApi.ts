import type { EnterpriseModStack } from '@/constants/enterpriseModStack'
import { buildEnterpriseModStack } from '@/constants/enterpriseModStack'
import {
  fetchIndustryBaseline,
  fetchOnboardingIndustryCatalog,
} from '@/utils/platformShellApi'
import { fetchWorkspacePrefs } from '@/utils/workspacePrefsApi'

let cachedStack: EnterpriseModStack | null = null

function buildOfflineEnterpriseModStack(industryId: string): EnterpriseModStack {
  return buildEnterpriseModStack({
    industry_id: industryId || '通用',
    industry_package: null,
    groups: [],
    required_mod_ids: [],
    optional_mod_ids: [],
    industry_mod_ids: [],
    missing_required_mod_ids: [],
    missing_optional_mod_ids: [],
    missing_industry_mod_ids: [],
    baseline_ready: false,
    industry_mod_ready: false,
  })
}

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

  try {
    const plan = await fetchIndustryBaseline(industryId, force)
    cachedStack = buildEnterpriseModStack(plan)
  } catch {
    cachedStack = buildOfflineEnterpriseModStack(industryId)
  }
  return cachedStack
}

export function invalidateEnterpriseModStackCache(): void {
  cachedStack = null
}
