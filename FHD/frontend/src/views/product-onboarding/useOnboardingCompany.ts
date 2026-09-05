import { ref, watch } from 'vue'
import type { RouteLocationNormalizedLoaded } from 'vue-router'
import { authApi } from '@/api/auth'
import { useAccountProfileStore } from '@/stores/accountProfile'
import { readTenantScopedStorageItem, writeTenantScopedStorageItem } from '@/utils/tenantStorageScope'

const COMPANY_NAME_KEY = 'xcagi_onboarding_company_name'

export function useOnboardingCompany(route: RouteLocationNormalizedLoaded) {
  const account = useAccountProfileStore()
  const companyName = ref(String(route.query.company || account.companyBrand || account.tenantName || readTenantScopedStorageItem(COMPANY_NAME_KEY) || '').trim())
  const companySaving = ref(false)
  watch(companyName, (name) => {
    writeTenantScopedStorageItem(COMPANY_NAME_KEY, name)
  })

  async function saveCompanyName(): Promise<void> {
    const name = companyName.value.trim().replace(/\s+/g, ' ').slice(0, 256)
    if (!name) return
    companySaving.value = true
    try {
      const result = await authApi.updateCompanyBrand(name)
      if (!result || typeof result !== 'object' || !('success' in result) || result.success !== true) throw new Error('公司名称未保存，请重试')
      const saved = result as { company_brand?: string; tenant_name?: string }
      companyName.value = saved.company_brand || name
      account.companyBrand = companyName.value
      if (typeof saved.tenant_name === 'string') account.tenantName = saved.tenant_name
    } finally {
      companySaving.value = false
    }
  }

  return { companyName, companySaving, saveCompanyName }
}
