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
        没有账号？<router-link to="/register" class="link">注册</router-link>
      </p>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { api } from '../api'

const router = useRouter()
const route = useRoute()
const username = ref('')
const password = ref('')
const loading = ref(false)
const err = ref('')

async function doLogin() {
  loading.value = true
  err.value = ''
  try {
    const res = await api.login(username.value, password.value)
    localStorage.setItem('modstore_token', res.token)
    const redirect = route.query.redirect || '/'
    router.push(redirect)
  } catch (e) {
    err.value = e.message
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.auth-page { display: flex; justify-content: center; padding-top: 60px; }
.auth-card { background: #fff; border-radius: 12px; box-shadow: 0 2px 12px rgba(0,0,0,0.1); padding: 32px; width: 100%; max-width: 400px; }
.auth-card h2 { font-size: 22px; margin-bottom: 24px; text-align: center; }
.form-group { margin-bottom: 16px; }
.form-group label { display: block; font-size: 13px; color: #666; margin-bottom: 6px; }
.btn-block { width: 100%; }
.auth-footer { text-align: center; margin-top: 16px; font-size: 14px; color: #666; }
.link { color: #4361ee; }
</style>
