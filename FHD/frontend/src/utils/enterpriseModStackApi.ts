import type { EnterpriseModStack } from '@/constants/enterpriseModStack'
import { buildEnterpriseModStack } from '@/constants/enterpriseModStack'
import { fetchIndustryBaseline, fetchOnboardingIndustryCatalog } from '@/utils/platformShellApi'
import { fetchWorkspacePrefs } from '@/utils/workspacePrefsApi'
import { employeeDirectoryScope } from '@/api/employeeDirectory'

let cachedStack: EnterpriseModStack | null = null
let cachedScope = ''
let requestGeneration = 0

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
  const scope = employeeDirectoryScope()
  if (cachedStack && cachedScope === scope && !force) return cachedStack
  const generation = ++requestGeneration

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

  let stack: EnterpriseModStack
  try {
    const plan = await fetchIndustryBaseline(industryId, force)
    stack = buildEnterpriseModStack(plan)
  } catch {
    stack = buildOfflineEnterpriseModStack(industryId)
  }
  if (scope !== employeeDirectoryScope()) throw new Error('企业工作空间上下文已变更，请重试')
  if (generation === requestGeneration) {
    cachedStack = stack
    cachedScope = scope
  }
  return stack
}

export function invalidateEnterpriseModStackCache(): void {
  cachedStack = null
  requestGeneration++
}
