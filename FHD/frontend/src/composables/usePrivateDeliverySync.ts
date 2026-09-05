import { onBeforeUnmount, onMounted, readonly, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useAccountProfileStore } from '@/stores/accountProfile'
import { useModsStore } from '@/stores/mods'
import { registerModRoutes, type ModRouteApiEntry } from '@/router/registerModRoutes'
import { apiFetch } from '@/utils/apiBase'
import { showAppNotification } from '@/composables/useAppToast'

export type PrivateDeliverySyncResult = {
  routes_changed?: boolean
  installed: string[]
  restart_required: string[]
  pending: number
  errors: Array<{ mod_id: string; message: string }>
}

export function usePrivateDeliverySync() {
  const account = useAccountProfileStore()
  const mods = useModsStore()
  const router = useRouter()
  const result = ref<PrivateDeliverySyncResult | null>(null)
  const pending = ref(false)
  let mounted = false
  let generation = 0
  let timer: ReturnType<typeof setInterval> | undefined
  let controller: AbortController | undefined
  let refreshNeeded = false
  const restartNotified = new Set<string>()

  function active() {
    return mounted && account.loaded && Number(account.marketUserId) > 0
      && !account.impersonatingMarketUserId && !String(account.impersonatingUsername || '').trim()
      && (Number(account.localUserId) > 0 || Number(account.tenantId) > 0)
  }

  async function sync() {
    if (!active() || controller || navigator.onLine === false) return
    const current = generation
    const request = new AbortController()
    controller = request
    pending.value = true
    const alive = () => current === generation && !request.signal.aborted && active()
    try {
      const response = await apiFetch('/api/mod-store/private-delivery/sync', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
        signal: request.signal, timeoutMs: 45_000,
      })
      const body = await response.json()
      if (!alive()) return
      if (!response.ok || body.success !== true) { refreshNeeded = true; return }
      result.value = body.data as PrivateDeliverySyncResult
      const restarts: string[] = Array.isArray(body.data?.restart_required) ? body.data.restart_required : []
      for (const mid of restartNotified) if (!restarts.includes(mid)) restartNotified.delete(mid)
      if (restarts.some(mid => !restartNotified.has(mid))) {
        showAppNotification('私有扩展更新已就绪', '下次重启后生效')
        restarts.forEach(mid => restartNotified.add(mid))
      }
      refreshNeeded ||= body.data?.routes_changed === true || (Array.isArray(body.data?.installed) && body.data.installed.length > 0)
      if (!refreshNeeded) return
      // Abortable reads avoid an old account's delayed list entering a new store.
      const [listing, routes] = await Promise.all([
        apiFetch('/api/mods/', { signal: request.signal, timeoutMs: 15_000 }),
        apiFetch('/api/mods/routes', { signal: request.signal, timeoutMs: 15_000 }),
      ])
      const [listed, routed] = await Promise.all([listing.json(), routes.json()])
      if (!alive()) return
      if (!listing.ok || listed.success !== true || !Array.isArray(listed.data)
        || !routes.ok || routed.success !== true || !Array.isArray(routed.data)) return
      mods.mods = listed.data
      if (routes.ok && routed.success === true && Array.isArray(routed.data)) {
        // Only runtime routes need registering here; the built-in loader stays
        // with the normal startup path and never imports remote source code.
        mods.modRoutes = routed.data
        const runtime = (routed.data as ModRouteApiEntry[]).filter(row => row.runtime)
        await registerModRoutes(router, runtime)
        if (alive()) refreshNeeded = false
      }
    } catch {
      if (alive()) refreshNeeded = true
      // A failed background sync leaves the active page and next retry intact.
    } finally {
      if (current === generation) {
        controller = undefined
        pending.value = false
      }
    }
  }

  function reset() {
    generation += 1
    controller?.abort()
    controller = undefined
    pending.value = false
    result.value = null
    refreshNeeded = false
    if (timer !== undefined) clearInterval(timer)
    timer = undefined
    if (active()) {
      const current = generation
      // A profile hydration may update several identity fields in one tick.
      queueMicrotask(() => { if (current === generation) void sync() })
      timer = setInterval(() => { void sync() }, 60_000)
    }
  }

  const stop = watch(() => [account.loaded, account.marketUserId, account.tenantId,
    account.localUserId, account.impersonatingMarketUserId, account.impersonatingUsername],
  () => { restartNotified.clear(); reset() },
  { flush: 'sync' })
  const connectionChanged = () => {
    reset()
    // The disconnected request may have completed installation on the server.
    refreshNeeded = true
  }
  onMounted(() => {
    mounted = true
    window.addEventListener('online', connectionChanged)
    window.addEventListener('offline', connectionChanged)
    reset()
  })
  onBeforeUnmount(() => {
    mounted = false
    stop()
    reset()
    window.removeEventListener('online', connectionChanged)
    window.removeEventListener('offline', connectionChanged)
  })
  return { result: readonly(result), pending: readonly(pending), sync }
}
