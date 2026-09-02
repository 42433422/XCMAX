import { apiFetch } from '@/utils/apiBase'
import { installHostFoundation } from '@/api/modStore'
import { isHostFoundationEmployeePackId, readBuildEdition } from '@/constants/genericModPack'
import { autoOnboardInstalledMarketItem } from '@/utils/workflowEmployeeOnboard'
import { appAlert, appConfirm } from '@/utils/appDialog'
import type { useModsStore } from '@/stores/mods'
import type { ModStoreState, StoreModRow } from './useModStoreState'
import type { ModStoreCatalog } from './useModStoreCatalog'
import type { ModStoreMeta } from './useModStoreMeta'

type ModsStore = ReturnType<typeof useModsStore>

export interface ModStoreActionsDeps {
  modsStore: ModsStore
  catalog: Pick<ModStoreCatalog, 'loadMods'>
  meta: Pick<ModStoreMeta, 'isEmployeePackItem' | 'installSuccessMessage'>
}

export interface ModStoreActions {
  refreshHostMods: () => void
  installModSilent: (mod: StoreModRow) => Promise<{ success: boolean; message: string }>
  installMod: (mod: StoreModRow) => Promise<void>
  uninstallMod: (mod: StoreModRow) => Promise<void>
  updateMod: (mod: StoreModRow) => Promise<void>
  hasUpdate: (mod: StoreModRow) => boolean | string | undefined
  viewDetails: (mod: StoreModRow) => void
  onMobileUse: (mod: StoreModRow) => Promise<void>
}

/** 安装卸载域（由 ModStore.vue 机械切出，行为不变）：安装/卸载/更新/详情与宿主目录刷新 */
export function useModStoreActions(state: ModStoreState, deps: ModStoreActionsDeps): ModStoreActions {
  const { selectedMod } = state
  const { modsStore, catalog, meta } = deps

  const refreshHostMods = () => {
    void modsStore.refresh().catch((e) => {
      console.warn('[ModStore] modsStore.refresh:', e)
    })
  }

  const installModSilent = async (mod: StoreModRow): Promise<{ success: boolean; message: string }> => {
    if (isHostFoundationEmployeePackId(mod.pkg_id || mod.id)) {
      const edition = readBuildEdition()
      const data = await installHostFoundation(edition === 'minimal' ? 'minimal' : 'generic')
      return { success: Boolean(data.success), message: data.message || '' }
    }
    const payload = {
      pkg_id: mod.pkg_id || mod.id,
      version: mod.version,
      package_file: mod.package_file,
      activate: true,
      verify_signature: false,
    }
    const response = await apiFetch('/api/mod-store/install', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    const data = await response.json()
    const ok = Boolean(data.success)
    if (ok) {
      try {
        await autoOnboardInstalledMarketItem(mod)
      } catch (e) {
        console.warn('[ModStore] silent auto onboard failed:', e)
      }
    }
    return {
      success: ok,
      message: data.error || data.detail || data.message || '',
    }
  }

  const installMod = async (mod: StoreModRow): Promise<void> => {
    mod.installationInProgress = true
    try {
      let data
      if (isHostFoundationEmployeePackId(mod.pkg_id || mod.id)) {
        const edition = readBuildEdition()
        data = await installHostFoundation(edition === 'minimal' ? 'minimal' : 'generic')
      } else {
        const payload = {
          pkg_id: mod.pkg_id || mod.id,
          version: mod.version,
          package_file: mod.package_file,
          activate: true,
          verify_signature: false,
        }
        const response = await apiFetch('/api/mod-store/install', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        })
        data = await response.json()
      }

      if (data.success) {
        mod.is_installed = true
        await catalog.loadMods()
        refreshHostMods()
        let onboardNote = ''
        try {
          const { onboardedIds, plannerRefreshed, enterpriseStackLabel: stackLabel } = await autoOnboardInstalledMarketItem(mod)
          if (onboardedIds.length) {
            onboardNote = `，已上岗至企业 Mod「${stackLabel}」`
          } else if (plannerRefreshed && meta.isEmployeePackItem(mod)) {
            onboardNote = `，已注册至企业 Mod「${stackLabel}」`
          }
        } catch (e) {
          console.warn('[ModStore] auto onboard failed:', e)
        }
        await appAlert(meta.installSuccessMessage(mod, onboardNote))
      } else {
        await appAlert(`安装失败：${data.error || data.detail}`)
      }
    } catch (error) {
      console.error('Installation failed:', error)
      await appAlert('安装失败，请重试')
    } finally {
      mod.installationInProgress = false
    }
  }

  const uninstallMod = async (mod: StoreModRow): Promise<void> => {
    if (!(await appConfirm(`确定要卸载 MOD "${mod.name}" 吗？`, { danger: true }))) {
      return
    }

    mod.uninstallationInProgress = true
    try {
      const formData = new FormData()
      formData.append('mod_id', mod.id)
      formData.append('remove_files', 'true')

      const response = await apiFetch('/api/mod-store/uninstall', {
        method: 'POST',
        body: formData,
      })

      const data = await response.json()

      if (data.success) {
        mod.is_installed = false
        await appAlert(`MOD ${mod.name} 卸载成功！`)
        await catalog.loadMods()
        refreshHostMods()
      } else {
        await appAlert(`卸载失败：${data.error || data.detail}`)
      }
    } catch (error) {
      console.error('Uninstallation failed:', error)
      await appAlert('卸载失败，请重试')
    } finally {
      mod.uninstallationInProgress = false
    }
  }

  const updateMod = async (mod: StoreModRow): Promise<void> => {
    mod.updateInProgress = true
    try {
      const payload = {
        mod_id: mod.id,
        pkg_id: mod.pkg_id || mod.id,
        version: mod.new_version || mod.version,
        package_file: mod.package_file,
        verify_signature: false,
      }

      const response = await apiFetch('/api/mod-store/update', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })

      const data = await response.json()

      if (data.success) {
        mod.version = data.data.version
        await appAlert(`MOD ${mod.name} 更新成功！`)
        await catalog.loadMods()
        refreshHostMods()
      } else {
        await appAlert(`更新失败：${data.error || data.detail}`)
      }
    } catch (error) {
      console.error('Update failed:', error)
      await appAlert('更新失败，请重试')
    } finally {
      mod.updateInProgress = false
    }
  }

  const hasUpdate = (mod: StoreModRow): boolean | string | undefined => {
    return mod.is_installed && mod.new_version && mod.new_version !== mod.version
  }

  const viewDetails = (mod: StoreModRow): void => {
    selectedMod.value = mod
  }

  const onMobileUse = async (mod: StoreModRow): Promise<void> => {
    if (mod.is_installed) {
      viewDetails(mod)
      return
    }
    await installMod(mod)
  }

  return {
    refreshHostMods,
    installModSilent,
    installMod,
    uninstallMod,
    updateMod,
    hasUpdate,
    viewDetails,
    onMobileUse,
  }
}
