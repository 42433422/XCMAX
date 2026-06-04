import type { RouteRecordRaw } from 'vue-router'

export const printRoutes: RouteRecordRaw[] = [
  {
    path: '/print',
    name: 'print',
    component: () => import('../../views/PrintView.vue'),
    meta: { title: '打印管理' }
  },
  {
    path: '/printer-list',
    name: 'printer-list',
    component: () => import('../../views/PrinterListView.vue'),
    meta: { title: '打印机列表' }
  },
  {
    path: '/template-preview',
    name: 'template-preview',
    component: () => import('../../views/TemplatePreviewView.vue'),
    meta: { title: '模板预览' }
  },
  {
    path: '/label-editor',
    name: 'label-editor',
    component: () => import('../../views/LabelEditorView.vue'),
    meta: { title: '标签编辑器' }
  },
  {
    path: '/console',
    name: 'console',
    component: () => import('../../views/TemplatePreviewView.vue'),
    meta: { title: '模板预览' },
    beforeEnter: (_to, _from, next) => {
      next()
    }
  }
]
