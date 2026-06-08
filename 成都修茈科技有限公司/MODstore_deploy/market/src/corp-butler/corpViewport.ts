import { onBeforeUnmount, onMounted, ref, type Ref } from 'vue'

const MOBILE_MQ = '(max-width: 960px)'

/** 与官网 styles.css 移动端断点一致（汉堡菜单 / 联系页精简布局） */
export function isCorpMobileViewport(): boolean {
  if (typeof window === 'undefined') return false
  return window.matchMedia(MOBILE_MQ).matches
}

/** 响应式移动端判定（组件内使用） */
export function useCorpMobileViewport(): Ref<boolean> {
  const isMobile = ref(isCorpMobileViewport())
  onMounted(() => {
    const mq = window.matchMedia(MOBILE_MQ)
    const sync = () => {
      isMobile.value = mq.matches
    }
    sync()
    mq.addEventListener('change', sync)
    onBeforeUnmount(() => mq.removeEventListener('change', sync))
  })
  return isMobile
}

export function intakeFormPlacementHint(): string {
  return isCorpMobileViewport() ? '下方' : '左侧'
}
