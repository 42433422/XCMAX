<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { marketRegisterUrl, purchaseAuthorizationUrl } from '@/constants/loginBranding'

defineProps<{ enterprise: boolean }>()

const route = useRoute()
const registerRoute = computed(() => ({
  name: 'login-register' as const,
  query: route.query,
}))
const enterpriseRegisterUrl = marketRegisterUrl()
const enterprisePurchaseUrl = purchaseAuthorizationUrl()
</script>

<template>
  <nav class="login-account-actions" :aria-label="$t('login.accountActions')">
    <template v-if="enterprise">
      <a class="login-account-action" :href="enterpriseRegisterUrl" target="_blank" rel="noopener noreferrer">{{
        $t('login.registerEnterprise')
      }}</a>
      <a
        class="login-account-action login-account-action--primary"
        :href="enterprisePurchaseUrl"
        target="_blank"
        rel="noopener noreferrer"
        >{{ $t('login.purchaseAuthorization') }}</a
      >
    </template>
    <router-link v-else class="login-account-action" :to="registerRoute">{{ $t('login.register') }}</router-link>
  </nav>
</template>

<style scoped>
.login-account-actions {
  position: absolute;
  top: 24px;
  right: 28px;
  display: flex;
  align-items: center;
  gap: 8px;
}

.login-account-action {
  padding: 6px 14px;
  color: var(--xc-color-primary);
  background: var(--xc-color-primary-surface);
  border: 1px solid var(--xc-color-primary-soft);
  border-radius: var(--xc-radius-full);
  font-size: 13px;
  font-weight: 500;
  text-decoration: none;
  transition: var(--xc-transition-fast);
}

.login-account-action:hover {
  background: var(--xc-color-primary-soft);
}

.login-account-action--primary {
  color: #fff;
  border-color: var(--xc-color-primary);
  background: var(--xc-color-primary);
}

.login-account-action--primary:hover {
  color: #fff;
  background: var(--xc-color-primary-hover, #1d4ed8);
}

@media (max-width: 480px) {
  .login-account-actions {
    top: 16px;
    right: 16px;
  }
}
</style>
