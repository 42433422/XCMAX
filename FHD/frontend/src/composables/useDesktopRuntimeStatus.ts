import { computed, ref, type Ref } from 'vue'

interface Options {
  shouldHideVersion: Ref<boolean>
  fallbackVersion: string
  displayVersion: (version: string) => string
}

interface RuntimeHealth {
  status?: string
  version?: string
  degradedReasons?: unknown[]
  build?: {
    git_sha?: string
  }
}

interface DesktopRuntimeStatus {
  runtimeStatus?: string
  readyForUi?: boolean
  degraded?: boolean
  degradedReasons?: unknown[]
}

export function useDesktopRuntimeStatus(options: Options) {
  const healthAppVersion = ref('')
  const desktopShellVersion = ref('')
  const runtimeHealth = ref<RuntimeHealth | null>(null)
  const desktopRuntimeStatus = ref<DesktopRuntimeStatus | null>(null)
  const loading = ref(true)
  const errorText = ref('')
  let timer: number | null = null

  const sidebarAppVersionText = computed(() => {
    if (options.shouldHideVersion.value) return ''
    const shell = String(desktopShellVersion.value || options.fallbackVersion || '').trim()
    const backend = String(healthAppVersion.value || '').trim()
    if (shell && backend && shell !== backend) return '版本不一致'
    return options.displayVersion(shell || backend)
  })

  const sidebarAppVersionTitle = computed(() => {
    const shell = String(desktopShellVersion.value || options.fallbackVersion || '').trim()
    const backend = String(healthAppVersion.value || '').trim()
    const gitSha = String(runtimeHealth.value?.build?.git_sha || '').trim()
    return [
      shell ? `桌面/UI ${options.displayVersion(shell)}` : '',
      backend ? `后端 ${options.displayVersion(backend)}` : '',
      gitSha ? `Git ${gitSha.slice(0, 12)}` : '',
    ].filter(Boolean).join(' · ') || '当前应用版本未知'
  })

  const systemStatusTone = computed(() => {
    if (loading.value && !runtimeHealth.value) return 'loading'
    if (errorText.value && !runtimeHealth.value) return 'offline'
    const health = String(runtimeHealth.value?.status || '').toLowerCase()
    const desktop = String(desktopRuntimeStatus.value?.runtimeStatus || '').toLowerCase()
    if (health === 'unhealthy' || desktop === 'unhealthy') return 'offline'
    if (desktopRuntimeStatus.value && desktopRuntimeStatus.value.readyForUi === false) return 'loading'
    if (health === 'degraded' || desktop === 'degraded' || desktopRuntimeStatus.value?.degraded === true) return 'warning'
    return 'online'
  })

  const systemStatusText = computed(() => ({
    loading: '系统启动中', offline: '系统异常', warning: '系统降级', online: '系统正常',
  })[systemStatusTone.value] || '系统正常')

  const systemStatusTitle = computed(() => {
    const reasons = [
      ...(Array.isArray(runtimeHealth.value?.degradedReasons) ? runtimeHealth.value.degradedReasons : []),
      ...(Array.isArray(desktopRuntimeStatus.value?.degradedReasons) ? desktopRuntimeStatus.value.degradedReasons : []),
    ].map((item) => String(item || '').trim()).filter(Boolean)
    if (reasons.length) return `${systemStatusText.value}：${[...new Set(reasons)].join('；')}`
    if (errorText.value) return `${systemStatusText.value}：${errorText.value}`
    return systemStatusText.value
  })

  async function refresh(): Promise<void> {
    if (options.shouldHideVersion.value) return
    loading.value = true
    errorText.value = ''
    try {
      const [healthResult, desktopResult] = await Promise.allSettled([
        fetch('/api/health?lite=true', { credentials: 'same-origin' }),
        fetch('/api/desktop/status', { credentials: 'same-origin' }),
      ])
      if (healthResult.status !== 'fulfilled' || !healthResult.value.ok) throw new Error('后端健康检查不可达')
      const health = await healthResult.value.json()
      runtimeHealth.value = health && typeof health === 'object' ? health : null
      healthAppVersion.value = String(health?.version || '').trim()
      if (desktopResult.status === 'fulfilled' && desktopResult.value.ok) {
        const desktop = await desktopResult.value.json()
        desktopRuntimeStatus.value = desktop && typeof desktop === 'object' ? desktop : null
      } else {
        desktopRuntimeStatus.value = null
        errorText.value = '桌面运行时状态不可达'
      }
      if (window.xcagiDesktop?.getAppIdentity) {
        const identity = await window.xcagiDesktop.getAppIdentity().catch(() => null)
        desktopShellVersion.value = String(identity?.version || '').trim()
      }
    } catch (error) {
      runtimeHealth.value = null
      desktopRuntimeStatus.value = null
      errorText.value = error instanceof Error ? error.message : String(error || '状态未知')
    } finally {
      loading.value = false
    }
  }

  function startSystemStatusPolling(): void {
    if (timer != null) return
    void refresh()
    timer = window.setInterval(() => void refresh(), 30_000)
  }

  function stopSystemStatusPolling(): void {
    if (timer != null) window.clearInterval(timer)
    timer = null
  }

  return {
    sidebarAppVersionText, sidebarAppVersionTitle, systemStatusTone,
    systemStatusText, systemStatusTitle, startSystemStatusPolling, stopSystemStatusPolling,
  }
}
