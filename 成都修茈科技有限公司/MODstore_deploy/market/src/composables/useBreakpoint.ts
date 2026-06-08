import { ref, onMounted, onUnmounted } from 'vue'

const isMobile = ref(false)
const isTablet = ref(false)
const isDesktop = ref(true)

let initialized = false
let cleanupFn: (() => void) | null = null
let refCount = 0

function initListeners() {
  if (typeof window === 'undefined') return

  const mobileQuery = window.matchMedia('(max-width: 768px)')
  const tabletQuery = window.matchMedia('(min-width: 769px) and (max-width: 1024px)')

  function forceAndroidClient(): boolean {
    if (typeof window === 'undefined') return false
    const w = window as Window & { __XCAGI_CLIENT__?: string }
    if (w.__XCAGI_CLIENT__ === 'android') return true
    try {
      return new URLSearchParams(window.location.search).get('client') === 'android'
    } catch {
      return false
    }
  }

  function update() {
    const android = forceAndroidClient()
    isMobile.value = android || mobileQuery.matches
    isTablet.value = !android && tabletQuery.matches
    isDesktop.value = !isMobile.value && !isTablet.value
    if (android && typeof document !== 'undefined') {
      document.documentElement.classList.add('xcagi-client-android')
    }
  }

  update()

  mobileQuery.addEventListener('change', update)
  tabletQuery.addEventListener('change', update)
  window.addEventListener('xcagi-client-ready', update)

  cleanupFn = () => {
    mobileQuery.removeEventListener('change', update)
    tabletQuery.removeEventListener('change', update)
    window.removeEventListener('xcagi-client-ready', update)
  }

  initialized = true
}

export function useBreakpoint() {
  onMounted(() => {
    refCount++
    if (!initialized) {
      initListeners()
    }
  })

  onUnmounted(() => {
    refCount--
    if (refCount <= 0 && cleanupFn) {
      cleanupFn()
      cleanupFn = null
      initialized = false
      refCount = 0
    }
  })

  return { isMobile, isTablet, isDesktop }
}
