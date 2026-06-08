import { onBeforeUnmount, onMounted, ref } from 'vue'
import { loadPersonalSettings, resolveWorkbenchTheme } from '../utils/personalSettings'

/** 与 html[data-workbench-theme] / 个性化设置同步 */
export function useWorkbenchTheme() {
  const isLightTheme = ref(false)
  let themeObserver: MutationObserver | null = null

  function syncThemeFromDocument() {
    const onHtml = document.documentElement.dataset.workbenchTheme
    if (onHtml === 'light' || onHtml === 'dark') {
      isLightTheme.value = onHtml === 'light'
      return
    }
    isLightTheme.value = resolveWorkbenchTheme(loadPersonalSettings().theme) === 'light'
  }

  onMounted(() => {
    syncThemeFromDocument()
    themeObserver = new MutationObserver(syncThemeFromDocument)
    themeObserver.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['data-workbench-theme'],
    })
  })

  onBeforeUnmount(() => {
    themeObserver?.disconnect()
  })

  return { isLightTheme, syncThemeFromDocument }
}
