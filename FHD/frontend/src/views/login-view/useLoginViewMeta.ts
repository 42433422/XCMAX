import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { loginAccountInputPlaceholder, loginPasswordInputPlaceholder } from '@/constants/loginBranding'
import type { LoginViewState } from './useLoginViewState'

// LoginView 的标题/占位符/底部链接等纯展示计算属性（与拆分前逐字一致）
export function useLoginViewMeta(state: LoginViewState) {
  const { t } = useI18n()
  const route = useRoute()
  const { accountKind, productSku } = state

  const loginHeading = computed(() => (accountKind.value === 'admin' ? t('login.headingAdmin') : t('login.headingEnterprise')))
  const accountPlaceholder = computed(() => loginAccountInputPlaceholder(productSku.value))
  const passwordPlaceholder = computed(() => loginPasswordInputPlaceholder())
  const forgotAccountRoute = computed(() => ({
    name: 'login-forgot-account' as const,
    query: route.query,
  }))
  const forgotPasswordRoute = computed(() => ({
    name: 'login-forgot-password' as const,
    query: route.query,
  }))
  const loginHelpRoute = computed(() => ({
    name: 'login-help' as const,
    query: route.query,
  }))

  return {
    loginHeading,
    accountPlaceholder,
    passwordPlaceholder,
    forgotAccountRoute,
    forgotPasswordRoute,
    loginHelpRoute,
  }
}
