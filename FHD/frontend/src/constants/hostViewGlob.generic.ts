type ViewLoader = () => Promise<{ default: unknown }>

/** 干净通用宿主侧栏：智能对话 + 智能生态 + 员工工作流（+ 登录 / 设置路由） */
export const hostViewGlob = {
  ...import.meta.glob('../views/LoginView.vue'),
  ...import.meta.glob('../views/LoginHelpView.vue'),
  ...import.meta.glob('../views/RegisterView.vue'),
  ...import.meta.glob('../views/ForgotPasswordView.vue'),
  ...import.meta.glob('../views/ForgotAccountView.vue'),
  ...import.meta.glob('../views/ChatView.vue'),
  ...import.meta.glob('../views/AIEcosystemView.vue'),
  ...import.meta.glob('../views/OtherToolsView.vue'),
  ...import.meta.glob('../views/EmployeeWorkspaceView.vue'),
  ...import.meta.glob('../views/WorkflowVisualizationView.vue'),
  ...import.meta.glob('../views/SettingsView.vue'),
} as Record<string, ViewLoader>
