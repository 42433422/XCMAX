import { computed, ref, type Ref } from 'vue'
import { api } from '@/api'

/** 每日摘要行：模板/逻辑实际消费 ``id`` / ``recipients`` / ``body_html`` / ``body_text``，其余字段保持开放。 */
export interface DigestRow {
  [key: string]: unknown
  id: number
  recipients?: string[]
  body_html?: string
  body_text?: string
}

/** digest-identity 接口响应信封（后端 ``{ data: { digest_api_base, code } }``）。 */
interface DigestIdentityEnvelope {
  data?: { digest_api_base?: unknown; code?: unknown } | null
}

/** 每日摘要列表接口响应信封（兼容 data / records / data.items 数种后端形状）。 */
interface DigestListEnvelope {
  success?: boolean
  message?: unknown
  data?: unknown
  records?: unknown
}

/** 每日摘要详情接口响应信封。 */
interface DigestDetailEnvelope {
  data?: DigestRow | null
}

type TabKey = 'modules' | 'digests' | 'allHands'

/** 每日摘要存档 + 身份码徽章域逻辑（自 ServerFunctionsView.vue 拆出，行为零变更）。 */
export function useDigestPanel(activeTab: Ref<TabKey>) {
  const digestRecords = ref<DigestRow[]>([])
  const digestDetail = ref<DigestRow | null>(null)
  const selectedDigestId = ref<number | null>(null)
  const digestLoading = ref(false)
  const digestDetailLoading = ref(false)
  const digestError = ref('')
  const digestLastSynced = ref('')
  const DIGEST_POLL_INTERVAL_MS = 5 * 60 * 1000
  let digestPollTimer = 0
  const CACHE_KEY = 'xcmax_digest_identity_code'
  const CACHE_TTL_MS = 36 * 60 * 60 * 1000

  /** FHD 在 digest-identity 的 data 中注入，与 XCAGI_MARKET_BASE_URL 一致 */
  const digestApiBase = ref('')

  function readCachedIdentityCode(): string {
    try {
      const raw = localStorage.getItem(CACHE_KEY)
      if (!raw) return ''
      const obj = JSON.parse(raw)
      if (!obj?.code || !obj?.ts) return ''
      if (Date.now() - obj.ts > CACHE_TTL_MS) {
        localStorage.removeItem(CACHE_KEY)
        return ''
      }
      return obj.code
    } catch {
      return ''
    }
  }

  function writeCachedIdentityCode(code: string) {
    try {
      localStorage.setItem(CACHE_KEY, JSON.stringify({ code, ts: Date.now() }))
    } catch { /* quota exceeded etc. */ }
  }

  /** 服务端无有效身份码时清掉本地缓存，避免页眉仍显示过期码、与解锁/空摘要列表不一致。 */
  function clearDigestIdentityCache() {
    try {
      localStorage.removeItem(CACHE_KEY)
    } catch {
      /* ignore */
    }
    latestIdentityCode.value = ''
    digestApiBase.value = ''
  }

  const latestIdentityCode = ref(readCachedIdentityCode())
  const identityCopied = ref(false)
  let identityCopiedTimer = 0

  const marketWebFromDigest = computed(() => {
    const b = digestApiBase.value.trim().replace(/\/$/, '')
    if (!/^https?:\/\//i.test(b)) return ''
    return `${b}/market`
  })

  const identityBadgeTitle = computed(() => {
    const base = digestApiBase.value.trim()
    const tail = base
      ? ` 当前签发 API：${base}。解锁须在该 API 对应的修茈市场（通常 ${base}/market）提交本码，与 POST /api/auth/verify-admin-digest-code 同源。`
      : ''
    return `修茈市场管理端解锁用；由服务器 /api/xcmax/admin/digest-identity 与解锁校验同源。选中历史摘要不改变此码。点击复制。${tail}`
  })

  const selectedDigest = computed(() =>
    digestRecords.value.find((row) => Number(row.id) === Number(selectedDigestId.value)) || null,
  )

  function extractDigestIdentityCode(html: string): string {
    const m = html.match(/身份校验码[\s\S]*?<code[^>]*>([0-9A-Fa-f]{6})<\/code>/i)
    return m ? String(m[1]).toUpperCase() : ''
  }

  /** 与 MODstore ``digest_identity`` 模块一致：优先走同源接口，旧服务器再解析 HTML。 */
  async function syncDigestIdentityBadge(fallbackHtml?: string) {
    let digestIdentityApiOk = false
    try {
      const res = await api.get<DigestIdentityEnvelope>('/api/xcmax/admin/digest-identity')
      digestIdentityApiOk = true
      const d = res?.data && typeof res.data === 'object' ? res.data : null
      if (d && d.digest_api_base != null) {
        digestApiBase.value = String(d.digest_api_base).trim()
      }
      const c = d?.code ? String(d.code).trim().toUpperCase() : ''
      if (c.length === 6 && /^[0-9A-F]{6}$/.test(c)) {
        latestIdentityCode.value = c
        writeCachedIdentityCode(c)
        return
      }
    } catch {
      /* 远端未提供 digest-identity 时由 HTML 后备 */
    }
    if (fallbackHtml) {
      const code = extractDigestIdentityCode(fallbackHtml)
      if (code) {
        digestApiBase.value = ''
        latestIdentityCode.value = code
        writeCachedIdentityCode(code)
        return
      }
    }
    // 接口已成功但无有效码：清掉旧缓存（否则页眉长期显示与「暂无摘要」矛盾的过期身份码）
    if (digestIdentityApiOk) {
      clearDigestIdentityCache()
    }
  }

  function copyIdentityCode() {
    const code = latestIdentityCode.value
    if (!code) return
    const done = () => {
      identityCopied.value = true
      window.clearTimeout(identityCopiedTimer)
      identityCopiedTimer = window.setTimeout(() => {
        identityCopied.value = false
      }, 1500)
    }
    const w = navigator.clipboard?.writeText
    if (typeof w === 'function') {
      void w.call(navigator.clipboard, code).then(done).catch(fallbackCopyPlainText)
      return
    }
    fallbackCopyPlainText()

    function fallbackCopyPlainText() {
      try {
        const ta = document.createElement('textarea')
        ta.value = code
        ta.setAttribute('readonly', '')
        ta.style.position = 'fixed'
        ta.style.left = '-9999px'
        ta.style.top = '0'
        document.body.appendChild(ta)
        ta.focus()
        ta.select()
        const ok = document.execCommand('copy')
        document.body.removeChild(ta)
        if (ok) done()
      } catch {
        /* 非 HTTPS / 无剪贴板权限时静默失败 */
      }
    }
  }

  function normalizeDigestListPayload(res: DigestListEnvelope | DigestRow[] | null): DigestRow[] {
    if (Array.isArray(res)) {
      const arr = res as DigestRow[] & Partial<DigestListEnvelope>
      if (Array.isArray(arr.data)) return arr.data
      if (Array.isArray(arr.records)) return arr.records
      return res
    }
    if (Array.isArray(res?.data)) return res.data
    if (Array.isArray(res?.records)) return res.records
    const data = res?.data
    if (data && typeof data === 'object' && Array.isArray((data as { items?: unknown }).items)) {
      return (data as { items: DigestRow[] }).items
    }
    return []
  }

  async function loadDigestRecords() {
    digestLoading.value = true
    digestError.value = ''
    try {
      const res = await api.get<DigestListEnvelope>('/api/xcmax/admin/daily-digests', { limit: 30 })
      if (res && typeof res === 'object' && res.success === false) {
        throw new Error(String(res.message || '读取每日摘要失败'))
      }
      const rows = normalizeDigestListPayload(res)
      digestRecords.value = rows
      digestLastSynced.value = new Date().toLocaleTimeString()
      await syncDigestIdentityBadge()
      if (rows.length) {
        const latestId = Number(rows[0].id)
        if (!latestIdentityCode.value) {
          try {
            const detailRes = await api.get<DigestDetailEnvelope>(`/api/xcmax/admin/daily-digests/${latestId}`)
            const html = detailRes?.data?.body_html || ''
            await syncDigestIdentityBadge(String(html))
          } catch { /* best-effort */ }
        }
        if (!selectedDigestId.value || !rows.some((r) => Number(r.id) === Number(selectedDigestId.value))) {
          await selectDigest(latestId)
        }
      }
    } catch (e) {
      digestError.value = e instanceof Error ? e.message : String(e)
    } finally {
      digestLoading.value = false
    }
  }

  async function selectDigest(id: number) {
    selectedDigestId.value = id
    digestDetailLoading.value = true
    digestError.value = ''
    try {
      const res = await api.get<DigestDetailEnvelope>(`/api/xcmax/admin/daily-digests/${id}`)
      digestDetail.value = res?.data && typeof res.data === 'object' ? res.data : selectedDigest.value
    } catch (e) {
      digestError.value = e instanceof Error ? e.message : String(e)
    } finally {
      digestDetailLoading.value = false
    }
  }

  function stopDigestPolling() {
    if (digestPollTimer) {
      window.clearTimeout(digestPollTimer)
      digestPollTimer = 0
    }
  }

  function startDigestPolling() {
    stopDigestPolling()
    digestPollTimer = window.setTimeout(() => {
      if (activeTab.value === 'digests') {
        void loadDigestRecords().then(() => startDigestPolling())
      } else {
        startDigestPolling()
      }
    }, DIGEST_POLL_INTERVAL_MS)
  }

  async function fetchLatestIdentityCode() {
    try {
      await syncDigestIdentityBadge()
    } catch { /* best-effort */ }
  }

  return {
    digestRecords,
    digestDetail,
    selectedDigestId,
    digestLoading,
    digestDetailLoading,
    digestError,
    digestLastSynced,
    digestApiBase,
    latestIdentityCode,
    identityCopied,
    marketWebFromDigest,
    identityBadgeTitle,
    copyIdentityCode,
    loadDigestRecords,
    selectDigest,
    stopDigestPolling,
    startDigestPolling,
    fetchLatestIdentityCode,
  }
}
