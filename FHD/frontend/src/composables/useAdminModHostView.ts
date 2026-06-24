import { defineComponent, h, shallowRef, type Component } from 'vue'
import { RouterLink } from 'vue-router'
import ModRequiredView from '@/components/ModRequiredView.vue'

const modRuntimeViewLoaders = import.meta.glob(
  '../../../mods-admin-runtime/*/frontend/views/*.vue',
) as Record<string, () => Promise<{ default: Component }>>

function loaderKey(modId: string, viewFile: string): string {
  return `../../../mods-admin-runtime/${modId}/frontend/views/${viewFile}.vue`
}

/**
 * 加载中占位视图：复用全局 page-view/card 样式与 Font Awesome 旋转图标，
 * 在 Mod 物理视图异步加载完成前展示，避免误显「未安装」错误态。
 */
const ModLoadingView = defineComponent({
  name: 'ModLoadingView',
  props: { title: { type: String, default: '' } },
  setup(props) {
    return () =>
      h('div', { class: 'page-view mod-loading-view' }, [
        h('div', { class: 'page-content' }, [
          h(
            'div',
            { class: 'card', style: 'max-width: 560px; margin: 48px auto; padding: 24px;' },
            [
              h('p', { class: 'muted', style: 'margin: 0; line-height: 1.6;' }, [
                h('i', { class: 'fa fa-spinner fa-spin', style: 'margin-right: 8px;' }),
                props.title ? `正在加载 ${props.title}…` : '加载中…',
              ]),
            ],
          ),
        ]),
      ])
  },
})

/**
 * Mod 物理视图加载失败占位视图：区分「文件不存在（真未安装）」与「加载出错（网络/超时/服务端）」。
 * 加载出错时展示错误详情与重试入口，避免把临时失败误判为「未安装」。
 */
const ModLoadErrorView = defineComponent({
  name: 'ModLoadErrorView',
  props: {
    modId: { type: String, required: true },
    title: { type: String, default: '' },
    message: { type: String, default: '' },
    onRetry: { type: Function, default: undefined },
  },
  setup(props) {
    return () =>
      h('div', { class: 'page-view mod-load-error-view' }, [
        h('div', { class: 'page-content' }, [
          h(
            'div',
            { class: 'card', style: 'max-width: 560px; margin: 48px auto; padding: 24px;' },
            [
              h('h2', { style: 'margin: 0 0 12px;' }, props.title || '加载失败'),
              h('p', { class: 'muted', style: 'margin: 0 0 16px; line-height: 1.6;' }, [
                '加载 Mod ',
                h('code', {}, props.modId),
                ` 的视图失败：${props.message || '未知错误'}。`,
                '可能是网络超时或服务暂时不可用，请重试；若问题持续，请确认 Mod 已正确部署。',
              ]),
              h(
                'div',
                {
                  class: 'mod-required-actions',
                  style: 'display: flex; flex-wrap: wrap; gap: 8px;',
                },
                [
                  props.onRetry
                    ? h(
                        'button',
                        {
                          type: 'button',
                          class: 'btn btn-primary btn-sm',
                          onClick: () => props.onRetry?.(),
                        },
                        '重试',
                      )
                    : null,
                  h(
                    RouterLink,
                    { class: 'btn btn-secondary btn-sm', to: { name: 'mod-store' } },
                    () => '打开员工商店',
                  ),
                  h(
                    RouterLink,
                    { class: 'btn btn-secondary btn-sm', to: { name: 'chat' } },
                    () => '返回智能对话',
                  ),
                ],
              ),
            ],
          ),
        ]),
      ])
  },
})

/**
 * 宿主壳页加载 Mod 物理视图：优先 mods-admin-runtime（无需本机已安装 Mod 即可展示 UI）。
 * - 物理视图文件不存在 → ModRequiredView（真·未安装）。
 * - 加载期间 → ModLoadingView（加载中占位，而非误显错误态）。
 * - 加载失败 → ModLoadErrorView（展示错误详情 + 重试入口）。
 */
export function useAdminModHostView(modId: string, viewFile: string, title: string) {
  // 索引访问可能命中不到（Mod 未提供该物理视图），运行时按需判断。
  const load = modRuntimeViewLoaders[loaderKey(modId, viewFile)] as
    | (() => Promise<{ default: Component }>)
    | undefined
  const hasLoader = typeof load === 'function'

  // 无对应物理视图文件：Mod 确实未安装，直接回退 ModRequiredView。
  const View = shallowRef<Component>(hasLoader ? ModLoadingView : ModRequiredView)
  const modProps = { modId, title }

  function runLoad() {
    if (!load) return
    View.value = ModLoadingView
    void load()
      .then((m) => {
        View.value = m.default
      })
      .catch((err: unknown) => {
        const message = err instanceof Error ? err.message : String(err)
        View.value = defineComponent({
          name: 'ModLoadErrorViewBound',
          setup() {
            return () =>
              h(ModLoadErrorView, { modId, title, message, onRetry: runLoad })
          },
        })
      })
  }

  runLoad()

  return { View, modProps }
}
