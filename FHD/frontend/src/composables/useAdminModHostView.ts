import { shallowRef, type Component } from 'vue'
import ModRequiredView from '@/components/ModRequiredView.vue'

const modRuntimeViewLoaders = import.meta.glob(
  '../../../mods-admin-runtime/*/frontend/views/*.vue',
) as Record<string, () => Promise<{ default: Component }>>

function loaderKey(modId: string, viewFile: string): string {
  return `../../../mods-admin-runtime/${modId}/frontend/views/${viewFile}.vue`
}

/**
 * 宿主壳页加载 Mod 物理视图：优先 mods-admin-runtime（无需本机已安装 Mod 即可展示 UI）。
 * 仅当物理视图文件不存在时回退 ModRequiredView。
 */
export function useAdminModHostView(modId: string, viewFile: string, title: string) {
  const View = shallowRef<Component>(ModRequiredView)
  const modProps = { modId, title }

  const load = modRuntimeViewLoaders[loaderKey(modId, viewFile)]
  if (load) {
    void load()
      .then((m) => {
        View.value = m.default
      })
      .catch(() => {
        /* 保持 ModRequiredView */
      })
  }

  return { View, modProps }
}
