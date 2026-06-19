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
    const profile = buildRoleMenuProfile(
      {
        accountKind: accountProfileStore.accountKind,
        marketIsAdmin: accountProfileStore.marketIsAdmin,
        marketIsEnterprise: accountProfileStore.marketIsEnterprise,
        isAdminAccount: accountProfileStore.isAdminAccount,
      },
      isClientErpSidebarContext(
        (mods.value || []).map((m) => String(m.id || '').trim()),
        activeModId.value,
      ),
    )
    return canShowCoreMenuKey(profile, 'workflow-visualization')
  })

  return { showWorkflowPanoramaNav }
}
