// 拆分自 AiStoreView.vue：商品交互动作（点赞/收藏/下载/附加/下架/合集下载）。
import { ref } from 'vue'
import type { ComputedRef, Ref } from 'vue'
import type { Router } from 'vue-router'
import { api } from '../../api'
import { MOD_AUTHORING_ATTACH_KEY } from '../../features/mod-authoring/types'
import { ApiError } from '../../infrastructure/http/client'
import { useAuthStore } from '../../stores/auth'
import { isCatalogSaved, toggleCatalogSaved } from '../../utils/catalogSaved'
import type { AdminDigestUnlockOptions } from '../../composables/useAdminDigestUnlock'
import type { AiStoreItem } from './aiStoreTypes'

export interface AiStoreActionDeps {
  err: Ref<string>
  attachModId: ComputedRef<string>
  router: Router
  bundleDownloading: Ref<boolean>
  loadItems: (cacheBust?: boolean) => Promise<void>
  loadFacets: () => Promise<void>
  ensureAdminDigestUnlocked: (opts?: AdminDigestUnlockOptions) => Promise<boolean>
}

export function useAiStoreActions(deps: AiStoreActionDeps) {
  const { err, attachModId, router, bundleDownloading, loadItems, loadFacets, ensureAdminDigestUnlocked } = deps
  const authStore = useAuthStore()
  const delistingId = ref<number | string | null>(null)
  const downloadingId = ref<number | string | null>(null)
  const attachingId = ref<number | string | null>(null)
  const favBusyId = ref<number | string | null>(null)
  const savedRevision = ref(0)

  function isItemSaved(id: number | string | undefined) {
    savedRevision.value
    return isCatalogSaved(id)
  }

  function toggleSaved(item: AiStoreItem) {
    if (!item?.id) return
    toggleCatalogSaved(item.id)
    savedRevision.value++
  }

  async function toggleLike(item: AiStoreItem) {
    if (!item?.id || favBusyId.value) return
    if (!authStore.isLoggedIn) {
      err.value = '请先登录后再点赞'
      return
    }
    favBusyId.value = item.id
    err.value = ''
    try {
      const r = (await api.catalogToggleFavorite(item.id)) as { favorited?: boolean }
      const on = !!r.favorited
      const delta = on ? 1 : -1
      item.favorited = on
      item.favorite_count = Math.max(0, (item.favorite_count ?? 0) + delta)
    } catch (e: unknown) {
      err.value = e instanceof ApiError ? e.message : (e as Error)?.message || String(e)
    } finally {
      favBusyId.value = null
    }
  }

  async function downloadCard(item: AiStoreItem) {
    if (!item?.id || downloadingId.value) return
    if (!authStore.isLoggedIn) {
      err.value = '请先登录后再下载'
      return
    }
    downloadingId.value = item.id
    err.value = ''
    try {
      await api.downloadItem(item.id)
    } catch (e: unknown) {
      err.value = e instanceof ApiError ? e.message : (e as Error)?.message || String(e)
    } finally {
      downloadingId.value = null
    }
  }

  async function attachCardToMod(item: AiStoreItem) {
    const modId = attachModId.value
    const pkgId = String(item.pkg_id || '').trim()
    if (!modId || !pkgId || attachingId.value) return
    if (!authStore.isLoggedIn) {
      err.value = '请先登录后再添加到 Mod'
      return
    }
    if (item.artifact !== 'employee_pack') {
      err.value = '仅支持将 AI 员工包添加到 Mod'
      return
    }
    attachingId.value = item.id
    err.value = ''
    try {
      if (item.price > 0 && !item.purchased) {
        await api.buyItem(item.id)
        item.purchased = true
      }
      await api.attachCatalogEmployeeToMod(modId, {
        pkg_id: pkgId,
        catalog_item_id: typeof item.id === 'number' ? item.id : undefined,
      })
      try {
        sessionStorage.removeItem(MOD_AUTHORING_ATTACH_KEY)
      } catch {
        /* ignore */
      }
      await router.push({ name: 'mod-authoring', params: { modId } })
    } catch (e: unknown) {
      err.value = e instanceof ApiError ? e.message : (e as Error)?.message || String(e)
    } finally {
      attachingId.value = null
    }
  }

  async function downloadOfficeBundle() {
    if (!authStore.isLoggedIn) {
      err.value = '请先登录后再下载办公员工包'
      return
    }
    bundleDownloading.value = true
    err.value = ''
    try {
      await api.downloadOfficeEmployeePack()
    } catch (e: unknown) {
      err.value = e instanceof ApiError ? e.message : (e as Error)?.message || String(e)
    } finally {
      bundleDownloading.value = false
    }
  }

  async function downloadWorkflowBundle() {
    if (!authStore.isLoggedIn) {
      err.value = '请先登录后再下载工作流员工包'
      return
    }
    bundleDownloading.value = true
    err.value = ''
    try {
      await api.downloadWorkflowEmployeePack()
    } catch (e: unknown) {
      err.value = e instanceof ApiError ? e.message : (e as Error)?.message || String(e)
    } finally {
      bundleDownloading.value = false
    }
  }

  async function downloadHostFoundationPack() {
    if (!authStore.isLoggedIn) {
      err.value = '请先登录后再下载宿主基础员工包'
      return
    }
    bundleDownloading.value = true
    err.value = ''
    try {
      await api.downloadHostFoundationEmployeePack()
    } catch (e: unknown) {
      err.value = e instanceof ApiError ? e.message : (e as Error)?.message || String(e)
    } finally {
      bundleDownloading.value = false
    }
  }

  async function delistItem(item: AiStoreItem) {
    if (!item || delistingId.value) return
    const unlocked = await ensureAdminDigestUnlocked({
      title: '下架需身份校验',
      submitLabel: '验证',
      hint: '敏感操作：须输入与「解锁管理端」相同的 6 位身份码后方可下架商品。',
    })
    if (!unlocked) return
    const ok = window.confirm(`确定下架「${item.name}」吗？下架后 AI 市场将不再展示该商品。`)
    if (!ok) return
    delistingId.value = item.id
    err.value = ''
    try {
      await api.adminDeleteCatalog(item.id)
      await loadItems(true)
      await loadFacets()
    } catch (e: unknown) {
      err.value = e instanceof ApiError ? e.message : (e as Error)?.message || String(e)
    } finally {
      delistingId.value = null
    }
  }

  return {
    authStore,
    delistingId,
    downloadingId,
    attachingId,
    favBusyId,
    savedRevision,
    isItemSaved,
    toggleSaved,
    toggleLike,
    downloadCard,
    attachCardToMod,
    downloadOfficeBundle,
    downloadWorkflowBundle,
    downloadHostFoundationPack,
    delistItem,
  }
}
