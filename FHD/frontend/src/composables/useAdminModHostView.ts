import { ref, shallowRef, type Component } from 'vue'
import ModRequiredView from '@/components/ModRequiredView.vue'
import { findModViewLoader } from '@/router/modViews'

/**
 * 宿主壳页加载 Mod 物理视图。
 * 视图源统一走 modPhysicalViewGlob（按 edition 解析，SSOT = `mods/`），
 * 不再硬编码 mods-admin-runtime，避免两套 glob/目录漂移导致构建后视图回退。
 * 仅当物理视图文件不存在时回退 ModRequiredView。
 */
export function useAdminModHostView(modId: string, viewFile: string, title: string) {
  const View = shallowRef<Component>(ModRequiredView)
  const modProps = { modId, title }

  const load = findModViewLoader(modId, viewFile)
  const loading = ref(Boolean(load))
  if (load) {
    void load()
      .then((m) => {
        View.value = m.default as Component
      })
      .catch(() => {
        /* 保持 ModRequiredView */
      })
      .finally(() => {
        loading.value = false
      })
  }

  return { View, modProps, loading }
}
