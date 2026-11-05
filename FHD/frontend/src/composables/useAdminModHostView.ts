import { getCurrentScope, onScopeDispose, shallowRef, type Component } from 'vue'
import ModRequiredView from '@/components/ModRequiredView.vue'
import { findModViewLoader } from '@/router/modViews'
import { isChunkLoadError, markRouteChunkError } from '@/utils/routeLoadState'

/**
 * 宿主壳页加载 Mod 物理视图。
 * 视图源统一走 modPhysicalViewGlob（按 edition 解析，SSOT = `mods/`），不再硬编码
 * mods-admin-runtime；仅当物理视图不存在（或加载确实失败）时回退 ModRequiredView。
 */
export function useAdminModHostView(modId: string, viewFile: string, title: string) {
  const modProps = { modId, title }

  let disposed = false
  if (getCurrentScope()) {
    onScopeDispose(() => {
      disposed = true
    })
  }

  const load = findModViewLoader(modId, viewFile)
  // 有 loader 时先留空：首启 chunk 冷加载期间若显示 ModRequiredView 会闪出「未安装」假告警（宿主 v-if 兜住 null）
  const View = shallowRef<Component | null>(load ? null : ModRequiredView)
  if (load) {
    void load()
      .then((m) => {
        // 路由已切走时不再替换组件，避免对已卸载子树继续 patch 引发 insertBefore 空值异常。
        if (!disposed && m.default) View.value = m.default as Component
      })
      .catch((error: unknown) => {
        if (!disposed) View.value = ModRequiredView
        if (isChunkLoadError(error)) {
          markRouteChunkError(window.location.pathname || '/')
        }
      })
  }

  return { View, modProps }
}
