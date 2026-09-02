// 拆分自 App.vue：管理端解锁弹窗 + 管理端路由进入（逻辑逐字迁移，行为不变）。
import { ref } from 'vue'
import type { Ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api'
import { useAuthStore } from '../stores/auth'

export interface AdminUnlockDeps {
  isAdmin: Ref<boolean>
  currentMode: Ref<'client' | 'admin'>
}

export function useAdminUnlock(deps: AdminUnlockDeps) {
  const { isAdmin, currentMode } = deps
  const router = useRouter()
  const authStore = useAuthStore()

  const pendingAdminRouteName = ref<string | null>(null)
  const adminUnlockOpen = ref(false)
  const adminUnlockCode = ref('')
  const adminUnlockErr = ref('')
  const adminUnlockBusy = ref(false)

  function normalizeAdminUnlockCode(raw: string): string {
    return (raw || '').replace(/[^0-9A-Fa-f]/gi, '').toUpperCase().slice(0, 6)
  }

  /** 失焦时把「A 5 0 6 E 7」收成连续 6 位，避免误以为带空格也能原样提交。 */
  function onAdminUnlockInputBlur() {
    const hex = normalizeAdminUnlockCode(adminUnlockCode.value || '')
    adminUnlockCode.value = hex
  }

  function openAdminUnlockModal() {
    adminUnlockCode.value = ''
    adminUnlockErr.value = ''
    adminUnlockOpen.value = true
  }

  function closeAdminUnlockModal() {
    adminUnlockBusy.value = false
    adminUnlockOpen.value = false
    pendingAdminRouteName.value = null
  }

  async function submitAdminUnlock() {
    const raw = normalizeAdminUnlockCode(adminUnlockCode.value || '')
    if (raw.length !== 6 || !/^[0-9A-F]{6}$/.test(raw)) {
      adminUnlockErr.value = '请输入恰好 6 位十六进制（0–9、A–F），可从 XCmax 身份码或摘要邮件复制，勿填示例'
      return
    }
    adminUnlockBusy.value = true
    adminUnlockErr.value = ''
    adminUnlockCode.value = raw
    const VERIFY_MS = 45000
    let verifyTimer: number | undefined
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
        adminUnlockErr.value = '校验失败：请粘贴页眉身份码或当日摘要中的 6 位码（勿含空格/示例），或刷新 XCmax 后重试'
        return
      }
      authStore.setAdminDigestUnlock(String(res.expires_at || ''))
      adminUnlockOpen.value = false
      currentMode.value = 'admin'
      const target = pendingAdminRouteName.value || 'admin-database'
      pendingAdminRouteName.value = null
      void router.push({ name: target })
    } catch (e) {
      const baseMsg = e instanceof Error ? e.message : String(e)
      const hint =
        /身份码无效|已过期|校验失败|400/i.test(baseMsg) &&
        !/MODSTORE_DIGEST|UPSTREAM|digest_api/i.test(baseMsg)
          ? ' 请确认：浏览器里打开的修茈市场与该身份码的 API 源一致（见 XCmax「服务器功能」页眉下方提示）。'
          : ''
      adminUnlockErr.value = baseMsg + hint
    } finally {
      adminUnlockBusy.value = false
    }
  }

  function enterAdminRoute(routeName: string) {
    if (isAdmin.value && !authStore.adminUiUnlocked) {
      pendingAdminRouteName.value = routeName
      openAdminUnlockModal()
      return
    }
    currentMode.value = 'admin'
    void router.push({ name: routeName })
  }

  return {
    pendingAdminRouteName,
    adminUnlockOpen,
    adminUnlockCode,
    adminUnlockErr,
    adminUnlockBusy,
    normalizeAdminUnlockCode,
    onAdminUnlockInputBlur,
    openAdminUnlockModal,
    closeAdminUnlockModal,
    submitAdminUnlock,
    enterAdminRoute,
  }
}
