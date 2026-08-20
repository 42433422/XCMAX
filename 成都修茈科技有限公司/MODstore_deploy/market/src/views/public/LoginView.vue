<template>
  <div class="auth-page">
    <div class="auth-card">
      <h2>登录</h2>
      <div v-if="err" class="flash flash-err">{{ err }}</div>
      <form @submit.prevent="doLogin">
        <div class="form-group">
          <label>用户名</label>
          <input class="input" v-model="username" required autocomplete="username" />
        </div>
        <div class="form-group">
          <label>密码</label>
          <input class="input" type="password" v-model="password" required autocomplete="current-password" />
        </div>
        <button type="submit" class="btn btn-primary-solid btn-block" :disabled="loading">
          {{ loading ? '登录中...' : '登录' }}
        </button>
      </form>
      <p class="auth-footer">
        <router-link to="/login-email" class="link">邮箱验证码登录</router-link>
        · <router-link to="/forgot-password" class="link">忘记密码</router-link>
        · 没有账号？<router-link :to="registerRoute" class="link">注册</router-link>
      </p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { pickRedirectFromRoute } from '@/authPaths'

const router = useRouter()
const route = useRoute()
const username = ref('')
const password = ref('')
const loading = ref(false)
const err = ref('')
const authStore = useAuthStore()
const registerRoute = computed(() => ({ name: 'register', query: route.query }))

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error || '登录失败')
}

async function doLogin() {
  loading.value = true
  err.value = ''
  try {
    await authStore.loginWithPassword(username.value, password.value)
    const dest = pickRedirectFromRoute(route)
    await router.replace(dest)
  } catch (e: unknown) {
    err.value = errorMessage(e)
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.auth-page {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  width: 100%;
  min-height: 0;
  box-sizing: border-box;
  padding: 0 var(--layout-pad-x, 16px) 1rem;
}
.auth-card {
  background: var(--wb-surface-elevated, #ffffff);
  border-radius: 12px;
  border: 0.5px solid var(--wb-border-default, rgba(0, 0, 0, 0.08));
  box-shadow: var(--wb-card-shadow, 0 8px 28px rgba(0, 0, 0, 0.06));
  padding: 32px;
  width: 100%;
  max-width: min(400px, 100%);
  box-sizing: border-box;
}
.auth-card h2 {
  font-size: 22px;
  margin-bottom: 24px;
  text-align: center;
  color: var(--wb-text-primary, #1d1d1f);
}
.form-group { margin-bottom: 16px; }
.form-group label {
  display: block;
  font-size: 13px;
  color: var(--wb-text-muted, #86868b);
  margin-bottom: 6px;
}
.btn-block { width: 100%; }
.auth-footer {
  text-align: center;
  margin-top: 16px;
  font-size: 14px;
  color: var(--wb-text-muted, #86868b);
}
.link {
  color: var(--wb-accent-primary, #0071e3);
  font-weight: 500;
}
</style>
