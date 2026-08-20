import { ref, onMounted, onUnmounted } from 'vue'

/** 响应式断点阈值；与 CSS 媒体查询共用，避免前后端断点漂移。 */
export const BREAKPOINTS = {
  /** 移动端最大宽度（含） */
  mobileMax: 768,
  /** 平板最大宽度（含） */
  tabletMax: 1024,
} as const

const isMobile = ref(false)
const isTablet = ref(false)
const isDesktop = ref(true)

let initialized = false
let cleanupFn: (() => void) | null = null
let refCount = 0

function initListeners() {
  if (typeof window === 'undefined') return

  const mobileQuery = window.matchMedia(`(max-width: ${BREAKPOINTS.mobileMax}px)`)
  const tabletQuery = window.matchMedia(`(min-width: ${BREAKPOINTS.mobileMax + 1}px) and (max-width: ${BREAKPOINTS.tabletMax}px)`)

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
