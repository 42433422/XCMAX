/**
 * 沙箱宿主发现/连接/推送视图逻辑（由 SandboxView.vue 原单文件机械迁出，行为不变）。
 */
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { useRoute } from 'vue-router'
import { sandboxApi } from '../../application/sandboxApi'
import { ApiError } from '../../infrastructure/http/client'

export function useSandboxHost() {
  const route = useRoute()

  /** 上次成功连上的宿主 API 根，供下次优先探测 */
  const SANDBOX_HOST_STORAGE = 'modstore_sandbox_last_host'
  /** 线上默认优先使用同源沙盒，不再先命中 http://域名:4173 导致 HTTPS 混合内容拦截 */
  const DEFAULT_SANDBOX_HOST_PATH = import.meta.env.VITE_SANDBOX_HOST_PATH || '/sandbox'

  const hostUrl = ref('')
  const connected = ref(false)
  const connecting = ref(false)
  const connectError = ref('')
  const probeProgress = ref('')
  const pushing = ref(false)
  const hostInfo = ref<Record<string, unknown> | null>(null)
  const iframeRef = ref<HTMLIFrameElement | null>(null)
  const manualModId = ref('')
  const pushMessage = ref('')

  const effectiveModId = computed(() => {
    const raw = route.query.modId || route.params.modId || manualModId.value
    return String(raw || '').trim()
  })

  const statusText = computed(() => {
    if (connected.value) return '已匹配'
    if (connecting.value) {
      return probeProgress.value ? `扫端口 (${probeProgress.value})` : '扫端口中'
    }
    return ''
  })

  const statusClass = computed(() => {
    return connected.value ? 'status-ok' : 'status-pending'
  })

  const iframeSrc = computed(() => {
    if (!connected.value || !hostUrl.value) return ''
    const base = hostUrl.value.replace(/\/+$/, '')
    return `${base}/?sandbox=1`
  })

  const isMixedContentBlocked = computed(() => {
    if (!connected.value || !hostUrl.value) return false
    try {
      const url = new URL(hostUrl.value)
      return window.location.protocol === 'https:' && url.protocol === 'http:' && !isLoopbackHost(url.hostname)
    } catch {
      return window.location.protocol === 'https:' && hostUrl.value.startsWith('http://') && !isLoopbackOrigin(hostUrl.value)
    }
  })

  function formatConnectFailure(e: unknown): string {
    if (e instanceof ApiError) return e.message || `请求失败（${e.status}）`
    if (e instanceof Error) return e.message
    return String(e)
  }

  /** 规范为「协议 + host」，供 /api/health 探测 */
  function normalizeHostOrigin(raw: unknown): string {
    const t = String(raw || '').trim()
    if (!t) return ''
    if (t.startsWith('/')) {
      return `${window.location.origin}${t}`.replace(/\/+$/, '')
    }
    try {
      const withProto = /^\w+:\/\//.test(t) ? t : `http://${t}`
      const u = new URL(withProto)
      if (u.protocol !== 'http:' && u.protocol !== 'https:') return ''
      return `${u.protocol}//${u.host}${u.pathname === '/' ? '' : u.pathname}${u.search}${u.hash}`.replace(/\/+$/, '')
    } catch {
      return t.replace(/\/+$/, '')
    }
  }

  function isLoopbackHost(hostname: unknown): boolean {
    const h = String(hostname || '')
      .trim()
      .toLowerCase()
    return h === 'localhost' || h === '127.0.0.1' || h === '[::1]' || h === '::1'
  }

  function isLoopbackOrigin(raw: unknown): boolean {
    try {
      return isLoopbackHost(new URL(normalizeHostOrigin(raw)).hostname)
    } catch {
      return false
    }
  }

  async function probeFromBrowser(url: string): Promise<Record<string, unknown> | null> {
    const base = normalizeHostOrigin(url)
    if (!base) return null
    const controller = new AbortController()
    const timer = window.setTimeout(() => controller.abort(), 1200)
    try {
      const sameOrigin = new URL(base).origin === window.location.origin
      // 本机端口必须从用户浏览器探测；线上后端访问 localhost 只会访问服务器自己。
      const resp = await fetch(`${base}/api/health`, {
        method: 'GET',
        mode: sameOrigin ? 'same-origin' : 'no-cors',
        cache: 'no-store',
        signal: controller.signal,
      })
      if (sameOrigin && !resp.ok) return null
      return { ok: true, host_url: base, source: 'browser-local' }
    } catch {
      return null
    } finally {
      window.clearTimeout(timer)
    }
  }

  function shouldProbeFromBrowser(url: string): boolean {
    if (isLoopbackOrigin(url)) return true
    try {
      return new URL(normalizeHostOrigin(url)).origin === window.location.origin
    } catch {
      return false
    }
  }

  /**
   * 本机 / 局域网常见 XCAGI FastAPI 与联调端口；线上 HTTPS 优先用 /sandbox，不再探测裸 HTTP 4173。
   * 每项为端口号，将拼成 http://127.0.0.1:{port} 与 http://localhost:{port}，并对当前页 hostname 复用。
   */
  const LOCAL_PROBE_PORTS = [5000, 5001, 5002, 5003, 5173, 5174, 5175, 5176, 5177, 3000, 8080, 8888, 8000, 8001]

  function addHostPortVariants(
    add: (value: string) => void,
    hostname: string,
    ports: number[],
    includeHttps: boolean,
    includeHttp = true,
  ): void {
    const h = String(hostname || '').trim()
    if (!h) return
    for (const p of ports) {
      if (includeHttps) add(`https://${h}:${p}`)
      if (includeHttp) add(`http://${h}:${p}`)
    }
  }

  /** 合并去重：URL 参数 → 同源 /sandbox → 输入框 → 上次成功 → 本机端口 → 当前页同机多端口扫描 */
  function buildDiscoveryCandidates() {
    const seen = new Set<string>()
    const out: string[] = []
    const add = (raw: unknown) => {
      const n = normalizeHostOrigin(raw)
      if (!n || seen.has(n)) return
      seen.add(n)
      out.push(n)
    }

    const q = route.query.host
    if (q) add(String(q))

    add(DEFAULT_SANDBOX_HOST_PATH)

    add(hostUrl.value)

    try {
      const s = localStorage.getItem(SANDBOX_HOST_STORAGE)
      if (s) add(s)
    } catch {
      /* ignore */
    }

    try {
      const { hostname, protocol } = window.location
      const p = String(window.location.port || '').trim()
      if (isLoopbackHost(hostname) && p && /^\d+$/.test(p) && p !== '80' && p !== '443') {
        add(`${protocol}//${hostname}:${p}`)
      }
    } catch {
      /* ignore */
    }

    addHostPortVariants(add, '127.0.0.1', LOCAL_PROBE_PORTS, false)
    addHostPortVariants(add, 'localhost', LOCAL_PROBE_PORTS, false)

    try {
      const { hostname, protocol } = window.location
      if (hostname && !isLoopbackHost(hostname)) {
        const isHttpsPage = protocol === 'https:'
        addHostPortVariants(add, hostname, LOCAL_PROBE_PORTS, isHttpsPage, !isHttpsPage)
      }
    } catch {
      /* ignore */
    }

    return out
  }

  /** 依次尝试候选地址，成功则写入输入框并记住 */
  async function discoverAndConnect() {
    if (connecting.value) return
    connecting.value = true
    connected.value = false
    hostInfo.value = null
    connectError.value = ''
    pushMessage.value = ''
    probeProgress.value = ''

    const list = buildDiscoveryCandidates()
    if (!list.length) {
      connectError.value = '请填写宿主 API 根地址（例如 http://127.0.0.1:5000）'
      connecting.value = false
      return
    }

    let lastApiError: unknown = null

    for (let i = 0; i < list.length; i++) {
      const url = list[i]
      hostUrl.value = url
      probeProgress.value = `${i + 1}/${list.length}`
      try {
        const result = shouldProbeFromBrowser(url) ? await probeFromBrowser(url) : await sandboxApi.connectHost(url)
        if (result && result.ok === true) {
          connected.value = true
          hostInfo.value = result
          try {
            localStorage.setItem(SANDBOX_HOST_STORAGE, url)
          } catch {
            /* ignore */
          }
          probeProgress.value = ''
          connecting.value = false
          return
        }
      } catch (e) {
        lastApiError = e
      }
    }

    probeProgress.value = ''
    if (lastApiError) {
      connectError.value = formatConnectFailure(lastApiError)
    } else {
      connectError.value = '未发现可连宿主（已试常用地址与当前页同机）。请确认 XCAGI 已启动后点「重新探测」，或手动填写 API 根地址。'
    }
    console.warn('[Sandbox] 探测结束，未找到可用宿主')
    connecting.value = false
  }

  async function pushAndTest() {
    if (!connected.value || pushing.value) return
    const modId = effectiveModId.value
    if (!modId) {
      pushMessage.value = '请先输入要测试的 Mod ID'
      return
    }
    pushing.value = true
    pushMessage.value = ''
    try {
      const result = await sandboxApi.pushAndTest(hostUrl.value, String(modId))
      if (result.ok) {
        if (iframeRef.value) {
          iframeRef.value.contentWindow?.postMessage({ type: 'sandbox:navigate', path: `/mod/${modId}` }, '*')
        }
        pushMessage.value = `已推送 ${modId}，正在宿主中打开测试页`
      } else {
        pushMessage.value = String(result.error || '推送失败，请检查 Mod ID 或宿主状态')
      }
    } catch (e) {
      console.warn('[Sandbox] 推送失败:', e)
      pushMessage.value = formatConnectFailure(e)
    } finally {
      pushing.value = false
    }
  }

  function openHostInNewTab() {
    const target = normalizeHostOrigin(iframeSrc.value)
    if (target) window.open(target, '_blank', 'noopener,noreferrer') // lgtm[js/client-side-unvalidated-url-redirection] validated HTTP(S), noopener
  }

  function openFullscreen() {
    if (!iframeRef.value) return
    const el = iframeRef.value as HTMLIFrameElement & { webkitRequestFullscreen?: () => void }
    if (el.requestFullscreen) el.requestFullscreen()
    else if (el.webkitRequestFullscreen) el.webkitRequestFullscreen()
  }

  function shouldAutoPush() {
    const raw = String(route.query.autoPush || '')
      .trim()
      .toLowerCase()
    return raw === '1' || raw === 'true' || raw === 'yes'
  }

  let messageHandler: ((event: MessageEvent) => void) | null = null

  onMounted(() => {
    messageHandler = (e: MessageEvent) => {
      if (e.data?.type === 'sandbox:ready') return
    }
    window.addEventListener('message', messageHandler)

    void discoverAndConnect().then(() => {
      if (connected.value && effectiveModId.value && shouldAutoPush()) {
        void pushAndTest()
      }
    })
  })

  onBeforeUnmount(() => {
    if (messageHandler) {
      window.removeEventListener('message', messageHandler)
      messageHandler = null
    }
  })

  return {
    hostUrl,
    connected,
    connecting,
    connectError,
    probeProgress,
    pushing,
    hostInfo,
    iframeRef,
    manualModId,
    pushMessage,
    effectiveModId,
    statusText,
    statusClass,
    iframeSrc,
    isMixedContentBlocked,
    normalizeHostOrigin,
    isLoopbackHost,
    isLoopbackOrigin,
    shouldProbeFromBrowser,
    buildDiscoveryCandidates,
    discoverAndConnect,
    pushAndTest,
    openHostInNewTab,
    openFullscreen,
    shouldAutoPush,
  }
}
