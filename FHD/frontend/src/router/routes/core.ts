import type { RouteRecordRaw } from 'vue-router'

/** 基础入口路由：index.html 重定向 / 登录系列 / 对话 / 独立工作区 / 知识库 / 局域网授权 */
export const CORE_ROUTES: RouteRecordRaw[] = [
  {
    path: '/index.html',
    redirect: (to) => ({ path: '/', query: to.query, hash: to.hash }),
  },
  {
    path: '/login',
    name: 'login',
    component: () => import('../../views/LoginView.vue'),
    meta: { title: '登录', publicAccess: true, hideChrome: true },
  },
  {
    path: '/login/help',
    name: 'login-help',
    component: () => import('../../views/LoginHelpView.vue'),
    meta: { title: '登录帮助', publicAccess: true, hideChrome: true },
  },
  {
    path: '/login/register',
    name: 'login-register',
    component: () => import('../../views/RegisterView.vue'),
    meta: { title: '注册', publicAccess: true, hideChrome: true },
  },
  {
    path: '/login/forgot-account',
    name: 'login-forgot-account',
    component: () => import('../../views/ForgotAccountView.vue'),
    meta: { title: '忘记账号', publicAccess: true, hideChrome: true },
  },
  {
    path: '/login/forgot-password',
    name: 'login-forgot-password',
    component: () => import('../../views/ForgotPasswordView.vue'),
    meta: { title: '忘记密码', publicAccess: true, hideChrome: true },
  },
  {
    path: '/',
    name: 'chat',
    component: () => import('../../views/ChatView.vue'),
    meta: { title: '智能对话' },
  },
  {
    path: '/workspaces/:taskId',
    name: 'task-workspace',
    component: () => import('../../views/ChatView.vue'),
    props: (route) => ({
      workspaceTaskId: String(route.params.taskId || ''),
      workspaceConversationId: String(route.query.conversation || route.params.taskId || ''),
    }),
    meta: { title: '独立工作区' },
  },
  {
    path: '/persy/knowledge',
    name: 'persy-knowledge',
    component: () => import('../../views/PersyKnowledgeView.vue'),
    meta: { title: 'Persy 知识库' },
  },
  {
    path: '/lan-gate',
    name: 'lan-gate',
    component: () => import('../../views/LanGateView.vue'),
    meta: { title: '局域网授权', publicAccess: true, hideChrome: true },
  },
]
