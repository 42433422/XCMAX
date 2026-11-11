import { getCurrentInstance, ref, watch } from 'vue'

/** 顶部搜索带过来的 keyword / focus。没有路由时保持为空，避免无路由的页面测试报错。 */
export function useRecordFocusQuery() {
  const keyword = ref('')
  const focusId = ref('')
  const router = getCurrentInstance()?.appContext.config.globalProperties.$router

  function sync(): void {
    const query = router?.currentRoute?.value?.query || {}
    keyword.value = String(query.keyword || '').trim()
    focusId.value = String(query.focus || '').trim()
  }

  if (router?.currentRoute) watch(() => [router.currentRoute.value.query?.keyword, router.currentRoute.value.query?.focus], sync, { immediate: true })
  return { keyword, focusId }
}
