<template>
  <div id="app">
    <nav class="navbar">
      <div class="nav-inner">
        <router-link to="/" class="nav-brand">MODstore 市场</router-link>
        <div class="nav-links">
          <router-link to="/" class="nav-link">市场</router-link>
          <template v-if="isLoggedIn">
            <router-link to="/my-store" class="nav-link">我的商店</router-link>
            <router-link to="/wallet" class="nav-link">钱包</router-link>
            <span class="nav-balance" v-if="balance !== null">¥{{ balance.toFixed(2) }}</span>
            <button class="nav-link btn-logout" @click="doLogout">退出</button>
          </template>
          <template v-else>
            <router-link to="/login" class="nav-link">登录</router-link>
            <router-link to="/register" class="nav-link btn-primary">注册</router-link>
          </template>
        </div>
      </div>
    </nav>
    <main class="main-content">
      <router-view />
    </main>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { api } from './api'

const isLoggedIn = ref(false)
const balance = ref(null)

onMounted(() => {
  isLoggedIn.value = !!localStorage.getItem('modstore_token')
  if (isLoggedIn.value) loadBalance()
})

async function loadBalance() {
  try {
    const res = await api.balance()
    balance.value = res.balance
  } catch {
    balance.value = null
  }
}

function doLogout() {
  localStorage.removeItem('modstore_token')
  isLoggedIn.value = false
  balance.value = null
  window.location.href = '/'
}
</script>

<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f5f5f5; color: #333; }
a { text-decoration: none; color: inherit; }

.navbar { background: #fff; border-bottom: 1px solid #e0e0e0; position: sticky; top: 0; z-index: 100; }
.nav-inner { max-width: 1200px; margin: 0 auto; padding: 0 20px; display: flex; align-items: center; justify-content: space-between; height: 56px; }
.nav-brand { font-size: 18px; font-weight: 700; color: #1a1a2e; }
.nav-links { display: flex; align-items: center; gap: 16px; }
.nav-link { font-size: 14px; color: #555; cursor: pointer; padding: 4px 8px; border-radius: 4px; transition: all 0.2s; }
.nav-link:hover { background: #f0f0f0; color: #1a1a2e; }
.nav-link.router-link-active { color: #4361ee; font-weight: 600; }
.nav-balance { font-size: 14px; color: #2d6a4f; font-weight: 600; background: #d8f3dc; padding: 4px 10px; border-radius: 12px; }
.btn-primary { background: #4361ee; color: #fff !important; }
.btn-primary:hover { background: #3a56d4; }
.btn-logout { border: 1px solid #ddd; }

.main-content { max-width: 1200px; margin: 0 auto; padding: 24px 20px; }

.flash { padding: 10px 16px; border-radius: 6px; margin-bottom: 16px; font-size: 14px; }
.flash-ok { background: #d8f3dc; color: #2d6a4f; }
.flash-err { background: #fde8e8; color: #c0392b; }

.card { background: #fff; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); padding: 20px; margin-bottom: 16px; }
.card-title { font-size: 16px; font-weight: 600; margin-bottom: 12px; }

.btn { display: inline-block; padding: 8px 16px; border-radius: 6px; font-size: 14px; cursor: pointer; border: 1px solid #ddd; background: #fff; transition: all 0.2s; }
.btn:hover { background: #f5f5f5; }
.btn-primary-solid { background: #4361ee; color: #fff; border: none; }
.btn-primary-solid:hover { background: #3a56d4; }
.btn-success { background: #2d6a4f; color: #fff; border: none; }
.btn-success:hover { background: #245a41; }
.btn-danger { background: #e74c3c; color: #fff; border: none; }
.btn-danger:hover { background: #c0392b; }
.btn:disabled { opacity: 0.5; cursor: not-allowed; }

.input { width: 100%; padding: 10px 12px; border: 1px solid #ddd; border-radius: 6px; font-size: 14px; outline: none; transition: border-color 0.2s; }
.input:focus { border-color: #4361ee; }

.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 16px; }
</style>
