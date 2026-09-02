// 拆分自 HomeView.vue：落地页登录态与工作台入口链接（逻辑逐字迁移，行为不变）。
import { computed, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '@/api'

export function useLandingAuth() {
  const router = useRouter()
  const isLoggedIn = ref(false)
  const username = ref('')
  const userEmail = ref('')

  const userLabel = computed(() => {
    const u = (username.value || '').trim()
    if (u) return u
    const e = (userEmail.value || '').trim()
    if (e) return e.split('@')[0] || e
    return '已登录'
  })

  /** 已登录直接去仓库工作台；未登录去登录页并带回跳，避免已登录点 /login 被守卫立即打回首页像「点不动」 */
  const workbenchLink = computed(() =>
    isLoggedIn.value
      ? '/workbench'
      : { path: '/login', query: { redirect: '/workbench' } },
  )

  async function refreshLandingAuth() {
    const raw = localStorage.getItem('modstore_token')
    const token = raw && raw !== 'undefined' && raw !== 'null' ? raw : ''
    if (!token) {
      isLoggedIn.value = false
      username.value = ''
      userEmail.value = ''
      if (raw) localStorage.removeItem('modstore_token')
      return
    }
    try {
      const me = await api.me()
      isLoggedIn.value = true
      username.value = typeof me.username === 'string' ? me.username : ''
      userEmail.value = typeof me.email === 'string' ? me.email : ''
    } catch {
      isLoggedIn.value = false
      username.value = ''
      userEmail.value = ''
    }
  }

  const stopAfterEach = router.afterEach((to) => {
    if (to.name === 'home') void refreshLandingAuth()
  })
  watch(
    () => router.currentRoute.value.name,
    (name) => {
      if (name === 'home') void refreshLandingAuth()
    },
  )
  onUnmounted(() => {
    stopAfterEach()
  })

  return {
    isLoggedIn,
    username,
    userEmail,
    userLabel,
    workbenchLink,
    refreshLandingAuth,
  }
}
