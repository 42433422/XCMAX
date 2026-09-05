import { computed, onActivated, onBeforeUnmount, onDeactivated, onMounted, ref } from 'vue'
import { authApi } from '@/api/auth'

/** Use the authenticated backend permission list; unknown permissions remain disabled. */
export function useEtlRollbackPermission() {
  const permissions = ref<string[]>([])
  const status = ref<'loading' | 'ready' | 'error'>('loading')
  let generation = 0
  let pending: Promise<void> | null = null

  function refresh() {
    if (pending) return pending
    const request = ++generation
    permissions.value = []
    status.value = 'loading'
    pending = (async () => {
      try {
        const result = await authApi.getCurrentUser()
        if (request !== generation) return
        if (!result.success || !Array.isArray(result.data?.permissions)) throw new Error('Permissions unavailable')
        permissions.value = result.data.permissions
        status.value = 'ready'
      } catch {
        if (request === generation) status.value = 'error'
      } finally {
        if (request === generation) pending = null
      }
    })()
    return pending
  }

  function reset() {
    generation += 1
    pending = null
    permissions.value = []
    status.value = 'loading'
  }

  const canRollback = computed(() => permissions.value.includes('etl.rollback'))
  const rollbackPermissionMessage = computed(() => {
    if (canRollback.value) return ''
    if (status.value === 'loading') return '正在确认撤销权限…'
    if (status.value === 'error') return '暂时无法确认撤销权限，请刷新页面重试。'
    return '撤销本次写入需要管理员授予撤销权限。'
  })

  onMounted(refresh)
  onActivated(refresh)
  onDeactivated(reset)
  onBeforeUnmount(reset)
  return { canRollback, rollbackPermissionMessage }
}
