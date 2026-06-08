import { ref, toRefs } from 'vue'
import { api } from '../api'
import { useAuthStore } from '../stores/auth'

export function normalizeAdminDigestCode(raw: string): string {
  return (raw || '').replace(/[^0-9A-Fa-f]/gi, '').toUpperCase().slice(0, 6)
}

const VERIFY_MS = 45_000

export type AdminDigestUnlockOptions = {
  title?: string
  submitLabel?: string
  hint?: string
}

/**
 * 与 App.vue「解锁管理端」相同：校验 6 位摘要身份码，成功后写入 sessionStorage 解锁态。
 */
export function useAdminDigestUnlock() {
  const authStore = useAuthStore()
  const open = ref(false)
  const code = ref('')
  const err = ref('')
  const busy = ref(false)
  const dialogTitle = ref('身份校验')
  const dialogSubmitLabel = ref('确认')
  const dialogHint = ref('')

  let pendingResolve: ((ok: boolean) => void) | null = null

  function onInputBlur() {
    code.value = normalizeAdminDigestCode(code.value)
  }

  function close() {
    busy.value = false
    open.value = false
    if (pendingResolve) {
      pendingResolve(false)
      pendingResolve = null
    }
  }

  async function submitVerify(): Promise<boolean> {
    const raw = normalizeAdminDigestCode(code.value)
    if (raw.length !== 6 || !/^[0-9A-F]{6}$/.test(raw)) {
      err.value = '请输入恰好 6 位十六进制（0–9、A–F），可从 XCmax 身份码或摘要邮件复制'
      return false
    }
    busy.value = true
    err.value = ''
    code.value = raw
    let verifyTimer: ReturnType<typeof setTimeout> | undefined
    const timeoutReject = new Promise<never>((_, rej) => {
      verifyTimer = window.setTimeout(
        () => rej(new Error(`校验请求超时（${VERIFY_MS / 1000}s），请检查网络或稍后重试`)),
        VERIFY_MS,
      )
    })
    try {
      const res = (await Promise.race([
        (api.verifyAdminDigestCode(raw) as Promise<{ ok?: boolean; expires_at?: string }>).finally(() => {
          if (verifyTimer !== undefined) window.clearTimeout(verifyTimer)
        }),
        timeoutReject,
      ])) as { ok?: boolean; expires_at?: string }
      if (!res?.ok) {
        err.value = '校验失败：请粘贴页眉身份码或当日摘要中的 6 位码（勿含空格/示例）'
        return false
      }
      authStore.setAdminDigestUnlock(String(res.expires_at || ''))
      open.value = false
      if (pendingResolve) {
        pendingResolve(true)
        pendingResolve = null
      }
      return true
    } catch (e) {
      const baseMsg = e instanceof Error ? e.message : String(e)
      const hint =
        /身份码无效|已过期|校验失败|400/i.test(baseMsg) &&
        !/MODSTORE_DIGEST|UPSTREAM|digest_api/i.test(baseMsg)
          ? ' 请确认浏览器所连市场 API 与身份码来源一致。'
          : ''
      err.value = baseMsg + hint
      return false
    } finally {
      busy.value = false
    }
  }

  /** 已解锁则直接 true；否则弹出校验框，用户取消为 false。 */
  function ensureAdminDigestUnlocked(opts?: AdminDigestUnlockOptions): Promise<boolean> {
    if (authStore.adminUiUnlocked) return Promise.resolve(true)
    dialogTitle.value = opts?.title || '身份校验'
    dialogSubmitLabel.value = opts?.submitLabel || '确认'
    dialogHint.value = opts?.hint || ''
    return new Promise((resolve) => {
      pendingResolve = resolve
      code.value = ''
      err.value = ''
      open.value = true
    })
  }

  return {
    ...toRefs({ open, code, err, busy, dialogTitle, dialogSubmitLabel, dialogHint }),
    onInputBlur,
    close,
    submitVerify,
    ensureAdminDigestUnlocked,
  }
}
