import { computed } from 'vue'
import { storeToRefs } from 'pinia'
import { useAccountProfileStore } from '@/stores/accountProfile'
import { useModsStore } from '@/stores/mods'
import { isClientErpSidebarContext } from '@/constants/genericModPack'
import { buildRoleMenuProfile, canShowCoreMenuKey } from '@/utils/roleMenuProfile'

/** 企业端隐藏「流程可视化」；管理端运维壳保留。 */
export function useWorkflowPanoramaNavVisible() {
  const accountProfileStore = useAccountProfileStore()
  const modsStore = useModsStore()
  const { mods, activeModId } = storeToRefs(modsStore)

  const showWorkflowPanoramaNav = computed(() => {
    const installedModIds = (mods.value || []).map((m) => String(m.id || '').trim())
    const isErp = isClientErpSidebarContext(installedModIds, activeModId.value)
    const profile = buildRoleMenuProfile(
      {
        accountKind: accountProfileStore.accountKind,
        marketIsAdmin: accountProfileStore.marketIsAdmin,
        marketIsEnterprise: accountProfileStore.marketIsEnterprise,
        isAdminAccount: accountProfileStore.isAdminAccount,
      },
      isErp,
    )
    // 企业客户 ERP 上下文隐藏「流程可视化」入口（该上下文有自身业务流程，避免重复）；
    // 管理端运维壳保留。侧边栏菜单可见性由 roleMenuProfile 独立控制，不受此影响。
    if (profile.role === 'enterprise-user' && isErp) return false
    return canShowCoreMenuKey(profile, 'workflow-visualization')
  })

  return { showWorkflowPanoramaNav }
}
