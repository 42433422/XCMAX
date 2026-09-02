// 拆分自 HomeView.vue：落地页顶栏导航状态（逻辑逐字迁移，行为不变）。
import { onUnmounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

export function useLandingNav() {
  const route = useRoute()
  const mobileNavOpen = ref(false)

  function toggleMobileNav() {
    mobileNavOpen.value = !mobileNavOpen.value
  }

  function closeMobileNav() {
    mobileNavOpen.value = false
  }

  watch(
    () => route.fullPath,
    () => {
      closeMobileNav()
    },
  )

  watch(mobileNavOpen, (open) => {
    if (typeof document === 'undefined') return
    document.body.classList.toggle('landing-nav-open', open)
  })

  onUnmounted(() => {
    if (typeof document !== 'undefined') {
      document.body.classList.remove('landing-nav-open')
    }
  })

  return {
    mobileNavOpen,
    toggleMobileNav,
    closeMobileNav,
  }
}
