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
        · 没有账号？<router-link to="/register" class="link">注册</router-link>
      </p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
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

async function doLogin() {
  loading.value = true
  err.value = ''
  try {
    await authStore.loginWithPassword(username.value, password.value)
    const dest = pickRedirectFromRoute(route)
    await router.replace(dest)
  } catch (e) {
    err.value = e.message
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
  background: #111111;
  border-radius: 12px;
  border: 0.5px solid rgba(255, 255, 255, 0.1);
  padding: 32px;
  width: 100%;
  max-width: min(400px, 100%);
  box-sizing: border-box;
}
.auth-card h2 { font-size: 22px; margin-bottom: 24px; text-align: center; color: #ffffff; }
.form-group { margin-bottom: 16px; }
.form-group label { display: block; font-size: 13px; color: rgba(255,255,255,0.5); margin-bottom: 6px; }
.btn-block { width: 100%; }
.auth-footer { text-align: center; margin-top: 16px; font-size: 14px; color: rgba(255,255,255,0.5); }
.link { color: #ffffff; font-weight: 500; }
</style>
