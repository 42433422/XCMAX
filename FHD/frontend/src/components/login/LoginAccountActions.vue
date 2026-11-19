<script setup lang="ts">
import { marketRegisterUrl } from '@/constants/loginBranding'

const registerUrl = marketRegisterUrl()
</script>

<template>
  <a class="login-account-actions login-account-action" :href="registerUrl" target="_blank" rel="noopener noreferrer">
    {{ $t('login.register') }}
  </a>
</template>

<style scoped>
.login-account-actions {
  position: absolute;
  top: 24px;
  right: 28px;
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

.login-account-action:hover { background: var(--xc-color-primary-soft); }

@media (max-width: 480px) {
  .login-account-actions {
    top: 16px;
    right: 16px;
  }
}
</style>
