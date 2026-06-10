<template>
  <div class="app-shell">
    <nav v-if="!isHome" class="navbar">
      <div class="nav-inner">
        <router-link to="/" class="nav-brand" @click="switchMode('client')">XC AGI</router-link>
        <div class="nav-links">
          <template v-if="isAdmin">
            <button :class="['mode-tab', { active: currentMode === 'client' }]" @click="switchMode('client')">客户端</button>
            <button :class="['mode-tab', { active: currentMode === 'admin' }]" @click="switchMode('admin')">管理端</button>
          </template>

          <template v-if="currentMode === 'admin' && isAdmin">
            <router-link to="/admin/database" class="nav-link nav-admin-link">数据库</router-link>
            <span class="nav-balance nav-badge">管理员模式</span>
          </template>

          <template v-else>
            <router-link to="/" class="nav-link">首页</router-link>
            <router-link to="/workbench/repository" class="nav-link">工作台</router-link>
            <router-link :to="{ name: 'ai-store' }" class="nav-link nav-gradient">AI 员工</router-link>
            <router-link to="/plans" class="nav-link">套餐</router-link>
            <template v-if="isLoggedIn">
              <router-link to="/my-store" class="nav-link">我的商店</router-link>
              <router-link to="/wallet" class="nav-link">钱包</router-link>
              <span v-if="balance !== null" class="nav-balance">¥{{ balance.toFixed(2) }}</span>
            </template>
          </template>

          <template v-if="isLoggedIn">
            <button class="nav-link btn-logout" @click="doLogout">退出</button>
          </template>
          <template v-else>
            <router-link to="/login" class="nav-link">登录</router-link>
            <router-link to="/register" class="nav-link btn-primary">注册</router-link>
          </template>
        </div>
      </div>
    </nav>
    <main class="main-content" :class="{ 'main-content--home': isHome }">
      <router-view />
    </main>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useRouter } from 'vue-router'
import { useAuthStore } from './stores/auth'
import { useWalletStore } from './stores/wallet'

const router = useRouter()
const authStore = useAuthStore()
const walletStore = useWalletStore()

const { isLoggedIn, isAdmin, currentMode } = storeToRefs(authStore)
const { balance } = storeToRefs(walletStore)

const isHome = ref(true)

onMounted(async () => {
  checkHome()
  await authStore.init()
  if (authStore.isLoggedIn) {
    void walletStore.refreshBalance()
  }
})

router.afterEach(() => {
  checkHome()
})

function checkHome(): void {
  isHome.value = router.currentRoute.value.path === '/'
}

watch(currentMode, (mode) => {
  if (mode === 'admin') {
    void router.push('/admin/database')
  } else {
    void router.push('/')
  }
})

function switchMode(mode: 'client' | 'admin'): void {
  authStore.setMode(mode)
}

async function doLogout(): Promise<void> {
  authStore.logout()
  walletStore.clear()
  await router.push('/')
}
</script>

<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
html, body { height: 100%; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0a0a0a; color: #ffffff; }
/* 挂载点 #app 在 index.html；随内容增高，至少一屏高 */
#app { min-height: 100%; display: flex; flex-direction: column; }
.app-shell { flex: 1 1 auto; display: flex; flex-direction: column; min-height: 100%; width: 100%; }
a { text-decoration: none; color: inherit; }

.navbar { background: #111111; border-bottom: 0.5px solid rgba(255,255,255,0.1); position: sticky; top: 0; z-index: 100; }
.nav-inner { max-width: 1200px; margin: 0 auto; padding: 0 20px; display: flex; align-items: center; justify-content: space-between; height: 56px; }
.nav-brand { font-size: 18px; font-weight: 700; color: #ffffff; }
.nav-links { display: flex; align-items: center; gap: 16px; }
.nav-link { font-size: 14px; color: rgba(255,255,255,0.5); cursor: pointer; padding: 4px 8px; border-radius: 4px; transition: all 0.2s; }
.nav-link:hover { background: rgba(255,255,255,0.06); color: #ffffff; }
.nav-link.router-link-active { color: #ffffff; font-weight: 600; }
.nav-balance { font-size: 14px; color: #4ade80; font-weight: 600; background: rgba(74,222,128,0.1); padding: 4px 10px; border-radius: 12px; }
.nav-badge { background: rgba(96,165,250,0.15); color: #60a5fa; font-size: 12px; font-weight: 700; }

.mode-tab { font-size: 13px; font-weight: 600; padding: 4px 10px; border-radius: 4px; cursor: pointer; border: none; background: transparent; color: rgba(255,255,255,0.35); transition: all 0.2s; }
.mode-tab:hover { color: rgba(255,255,255,0.7); }
.mode-tab.active { color: #ffffff; background: rgba(255,255,255,0.06); }

.nav-admin-link { color: #60a5fa !important; font-weight: 600; }

.nav-gradient {
  font-size: 13px;
  font-weight: 700;
  color: transparent;
  background: linear-gradient(135deg, #60a5fa, #818cf8);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}
.nav-link.nav-gradient:hover {
  opacity: 0.92;
}
.btn-primary { background: #ffffff; color: #0a0a0a !important; }
.btn-primary:hover { opacity: 0.9; }
.btn-logout { border: none; background-color: #1f1f1f; }

.main-content { flex: 1 1 auto; max-width: 1200px; width: 100%; margin: 0 auto; padding: 24px 20px; }
/* 首页落地页自带全宽布局，外层不再限 1200px */
.main-content--home { max-width: none; padding: 0; }

.flash { padding: 10px 16px; border-radius: 6px; margin-bottom: 16px; font-size: 14px; }
.flash-ok { background: rgba(74,222,128,0.1); color: #4ade80; }
.flash-err { background: rgba(255,80,80,0.1); color: #ff6b6b; }

.card { background: #111111; border-radius: 12px; border: 0.5px solid rgba(255,255,255,0.1); padding: 20px; margin-bottom: 16px; }
.card-title { font-size: 16px; font-weight: 600; margin-bottom: 12px; }

.btn { display: inline-block; padding: 8px 16px; border-radius: 8px; font-size: 14px; cursor: pointer; border: 0.5px solid rgba(255,255,255,0.15); background: #111111; color: #ffffff; transition: all 0.2s; }
.btn:hover { background: rgba(255,255,255,0.06); }
.btn-primary-solid { background: #ffffff; color: #0a0a0a; border: none; }
.btn-primary-solid:hover { opacity: 0.9; }
.btn-success { background: rgba(74,222,128,0.15); color: #4ade80; border: none; }
.btn-success:hover { background: rgba(74,222,128,0.25); }
.btn-danger { background: rgba(255,80,80,0.15); color: #ff6b6b; border: none; }
.btn-danger:hover { background: rgba(255,80,80,0.25); }
.btn:disabled { opacity: 0.5; cursor: not-allowed; }

.input { width: 100%; padding: 10px 12px; border: 0.5px solid rgba(255,255,255,0.15); border-radius: 8px; font-size: 14px; outline: none; transition: border-color 0.2s; background: rgba(255,255,255,0.03); color: #ffffff; }
.input:focus { border-color: rgba(255,255,255,0.3); }
.input::placeholder { color: rgba(255,255,255,0.3); }

.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 16px; }
</style>
