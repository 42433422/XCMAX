import { shallowRef, type Component } from 'vue'
import ModRequiredView from '@/components/ModRequiredView.vue'
import { findModViewLoader } from '@/router/modViews'

/**
 * 宿主壳页加载 Mod 物理视图。
 * 视图源统一走 modPhysicalViewGlob（按 edition 解析，SSOT = `mods/`），不再硬编码
 * mods-admin-runtime；仅当物理视图不存在（或加载确实失败）时回退 ModRequiredView。
 */
export function useAdminModHostView(modId: string, viewFile: string, title: string) {
  const modProps = { modId, title }

  const load = findModViewLoader(modId, viewFile)
  // 有 loader 时先留空：首启 chunk 冷加载期间若显示 ModRequiredView 会闪出「未安装」假告警（宿主 v-if 兜住 null）
  const View = shallowRef<Component | null>(load ? null : ModRequiredView)
  if (load) {
    void load()
      .then((m) => {
        View.value = m.default as Component
      })
      .catch(() => {
        View.value = ModRequiredView
      })
  }

  return { View, modProps }
}
