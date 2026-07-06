import { ref, type Ref } from 'vue'
import type { Router } from 'vue-router'

/** 导航超过该时长仍未确认才显示指示器，避免快速切换时闪烁 */
export const ROUTE_PENDING_DELAY_MS = 250

const pending = ref(false)
let installed = false
let showTimer: number | null = null

/**
 * 路由守卫等待指示：企业版冷启动守卫链（SKU/会话/账号档案）可能耗时数秒，
 * 期间 router-view 为空白。导航悬挂超过阈值时亮起加载指示。
 *
 * 必须在 createRouter 之后、`app.use(router)` 之前安装（vue-router 的初始导航
 * 在 install 时就会启动，晚于它注册的 beforeEach 拦不到冷启动导航）。
 */
export function installRoutePendingIndicator(router: Router): Ref<boolean> {
  if (installed) return pending
  installed = true

  const arm = () => {
    if (typeof window === 'undefined') return
    if (showTimer != null) return
    showTimer = window.setTimeout(() => {
      pending.value = true
    }, ROUTE_PENDING_DELAY_MS)
  }

  const settle = () => {
    if (showTimer != null) {
      window.clearTimeout(showTimer)
      showTimer = null
    }
    pending.value = false
  }

  router.beforeEach(() => {
    arm()
  })
  router.afterEach(() => {
    settle()
  })
  router.onError(() => {
    settle()
  })

  return pending
}

/** App 模板读取当前导航悬挂状态（安装发生在 router 模块） */
export function routePendingRef(): Ref<boolean> {
  return pending
}

/** 单测辅助：重置单例状态 */
export function resetRoutePendingForTests(): void {
  installed = false
  pending.value = false
  if (showTimer != null && typeof window !== 'undefined') {
    window.clearTimeout(showTimer)
  }
  showTimer = null
}
