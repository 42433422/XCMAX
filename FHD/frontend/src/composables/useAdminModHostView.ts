import { shallowRef, type Component } from 'vue'
import ModRequiredView from '@/components/ModRequiredView.vue'

const adminModViewLoaders =
  import.meta.env.VITE_XCMAX_ADMIN_CONSOLE === '1'
    ? (import.meta.glob('../../../mods-admin-runtime/*/frontend/views/*.vue') as Record<
        string,
        () => Promise<{ default: Component }>
      >)
    : ({} as Record<string, () => Promise<{ default: Component }>>)

function loaderKey(modId: string, viewFile: string): string {
  return `../../../mods-admin-runtime/${modId}/frontend/views/${viewFile}.vue`
}

/** 企业端：ModRequiredView；管理端：从 mods-admin-runtime 加载物理视图 */
export function useAdminModHostView(modId: string, viewFile: string, title: string) {
  const View = shallowRef<Component>(ModRequiredView)
  const modProps = { modId, title }

  if (import.meta.env.VITE_XCMAX_ADMIN_CONSOLE === '1') {
    const load = adminModViewLoaders[loaderKey(modId, viewFile)]
    if (load) {
      void load().then((m) => {
        View.value = m.default
      })
    }
  }

  return { View, modProps }
}
