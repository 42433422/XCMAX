import { ref } from 'vue'
import { api } from '@/api'
import { appAlert } from '@/utils/appDialog'
import { getPersonnelModApiBase } from '@/constants/personnelModApi'

/**
 * 服务器后台总览卡片的本地/远端状态、模块注册表、远端员工与最近错误。
 * 从 XCmaxAdminView.vue 逐字迁移，行为零变更。
 */
export function useXcmaxOverview() {
  const syncingEmployees = ref(false)

  const localStatus = ref({ ok: false, version: '', database: '', uptime: '', address: window.location.host })
  const remoteStatus = ref({
    reachable: false,
    latencyMs: null,
    version: '',
    deployTime: '',
    /** 与 ``/api/xcmax/admin/remote-status`` 返回的 host:port 一致，避免与后端 XCMAX_REMOTE_* 漂移 */
    address: '',
  })
  const modules = ref([])
  const remoteEmployees = ref([])
  const recentErrors = ref([])

  function sourceLabel(source) {
    const map = { local: '本地 Mod', remote: '服务器', core: '系统内置', employee: '员工包' }
    return map[source] || source || '未知'
  }

  async function loadLocalStatus() {
    try {
      const r = await api.get('/api/health')
      localStatus.value = {
        // 后端 /api/health 使用 status: "healthy"（见 fastapi_routes.__init__），与 "ok" 口径并存
        ok: r?.status === 'ok' || r?.status === 'healthy' || r?.ok === true,
        version: r?.version || r?.data?.version || '—',
        database: r?.database || 'ok',
        uptime: r?.uptime || '—',
        address: window.location.host
      }
    } catch {
      localStatus.value.ok = false
    }
  }

  async function loadRemoteStatus() {
    const t0 = Date.now()
    try {
      const r = await api.get('/api/xcmax/admin/remote-status')
      const d = r?.data && typeof r.data === 'object' ? r.data : r
      const reachable = d?.reachable === true
      const serverMs = d?.latency_ms
      const host = d?.host != null && d.host !== '' ? String(d.host) : ''
      const port = d?.port != null && d.port !== '' ? String(d.port) : ''
      const address = host && port ? `${host}:${port}` : host || '—'
      remoteStatus.value = {
        reachable,
        // 离线时后端 latency_ms 为 null；不要用「本接口总耗时」冒充远端延迟（会显示上万 ms）
        latencyMs:
          reachable && typeof serverMs === 'number' && !Number.isNaN(serverMs)
            ? serverMs
            : reachable
              ? Math.round(Date.now() - t0)
              : null,
        version: d?.version || '—',
        deployTime: d?.deploy_time || '—',
        address,
      }
    } catch {
      remoteStatus.value = {
        reachable: false,
        latencyMs: null,
        version: '—',
        deployTime: '—',
        address: '—',
      }
    }
  }

  async function loadModules() {
    try {
      const r = await api.get('/api/xcmax/admin/modules')
      if (r?.success && Array.isArray(r.data)) {
        modules.value = r.data
      }
    } catch {
      modules.value = []
    }
  }

  async function loadRemoteEmployees() {
    try {
      const base = getPersonnelModApiBase()
      const r = await api.get(`${base}/employees`, { page: 1, page_size: 200, search: '' })
      if (r?.success && r?.data?.items) {
        remoteEmployees.value = r.data.items.map(e => ({
          employee_id: e.employee_no || e.user_id || e.id,
          name: e.employee_name,
          domain: e.position,
          area: e.department,
          version: ''
        }))
      }
    } catch {
      remoteEmployees.value = []
    }
  }

  async function syncEmployees() {
    if (syncingEmployees.value) return
    syncingEmployees.value = true
    try {
      const res = await api.post(`${getPersonnelModApiBase()}/employees/sync-remote-yuangon`, {})
      if (!res?.success) throw new Error(res?.message || '同步失败')
      const d = res.data || {}
      await appAlert(`同步完成：${d.employees || 0} 名员工，${d.departments || 0} 个分组`)
      await loadRemoteEmployees()
    } catch (e) {
      recentErrors.value.unshift({ time: new Date().toLocaleTimeString(), message: `同步员工失败: ${e.message}` })
      await appAlert('同步员工失败: ' + (e.message || '未知错误'))
    } finally {
      syncingEmployees.value = false
    }
  }

  return {
    syncingEmployees,
    localStatus,
    remoteStatus,
    modules,
    remoteEmployees,
    recentErrors,
    sourceLabel,
    loadLocalStatus,
    loadRemoteStatus,
    loadModules,
    loadRemoteEmployees,
    syncEmployees,
  }
}
