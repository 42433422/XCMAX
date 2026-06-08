<template>
  <div class="workbench" :class="{ 'workbench--home': isWorkbenchHome }">
    <nav class="wb-scene-nav">
      <a :href="router.resolve({ name: 'workbench-home' }).href" class="wb-scene-nav-item" :class="{ 'wb-scene-nav-item--active': isWorkbenchHome }" @click.prevent="navigateTo({ name: 'workbench-home' })">
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"><path d="M2 2h5v5H2zM9 2h5v5H9zM2 9h5v5H2zM9 9h5v5H9z"/></svg>
        <span>首页</span>
      </a>
      <a :href="router.resolve({ name: 'workbench-unified', query: { focus: 'repository' } }).href" class="wb-scene-nav-item" :class="{ 'wb-scene-nav-item--active': isUnifiedRepo }" @click.prevent="navigateTo({ name: 'workbench-unified', query: { focus: 'repository' } })">
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"><rect x="1.5" y="1.5" width="13" height="13" rx="2"/><path d="M5 8h6M8 5v6"/></svg>
        <span>统一工作台</span>
      </a>
      <a :href="router.resolve({ name: 'workbench-script-workflows' }).href" class="wb-scene-nav-item" :class="{ 'wb-scene-nav-item--active': scriptWorkflowsNavActive }" @click.prevent="navigateTo({ name: 'workbench-script-workflows' })">
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"><path d="M2 4h12M2 8h8M2 12h5"/></svg>
        <span>脚本工作流</span>
      </a>
      <a :href="router.resolve({ name: 'workbench-employees' }).href" class="wb-scene-nav-item" :class="{ 'wb-scene-nav-item--active': myEmployeesNavActive }" @click.prevent="navigateTo({ name: 'workbench-employees' })">
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"><circle cx="8" cy="5" r="2.5"/><path d="M3 14c0-2.76 2.24-5 5-5s5 2.24 5 5"/></svg>
        <span>我的员工</span>
      </a>
      <a :href="router.resolve({ name: 'workbench-materials' }).href" class="wb-scene-nav-item" :class="{ 'wb-scene-nav-item--active': isMaterialsPage }" @click.prevent="navigateTo({ name: 'workbench-materials' })">
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"><path d="M2 2h4v4H2zM6 2h4v4H6zM10 2h4v4h-4zM2 6h4v4H2zM6 6h4v4H6z"/></svg>
        <span>我的素材</span>
      </a>
      <span class="wb-scene-nav-brand" aria-hidden="true">XC</span>
    </nav>
    <main class="workbench-main" :class="{ 'workbench-main--page-scroll': isPageScrollRoute }">
      <router-view v-slot="{ Component, route: childRoute }">
        <keep-alive :max="12">
          <component
            v-if="Component"
            :is="Component"
            :key="
              childRoute.name === 'mod-authoring'
                ? `mod-${String(childRoute.params?.modId || '')}`
                : String(childRoute.name || childRoute.fullPath)
            "
          />
        </keep-alive>
      </router-view>
    </main>
    <nav class="wb-mobile-tabbar">
      <a class="wb-mobile-tabbar-item" :class="{ 'wb-mobile-tabbar-item--active': isChatTab }" @click.prevent="navigateTo({ name: 'workbench-home' })">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
        <span>聊天</span>
      </a>
      <a class="wb-mobile-tabbar-item" :class="{ 'wb-mobile-tabbar-item--active': isEmployeeTab }" @click.prevent="navigateTo({ name: 'workbench-employees' })">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="7" r="4"/><path d="M5.5 21c0-4.14 2.92-7.5 6.5-7.5s6.5 3.36 6.5 7.5"/></svg>
        <span>员工</span>
      </a>
      <a class="wb-mobile-tabbar-item" :class="{ 'wb-mobile-tabbar-item--active': isMyTab }" @click.prevent="navigateTo({ name: 'workbench-materials' })">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
        <span>我的</span>
      </a>
    </nav>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'

const router = useRouter()
const route = useRoute()

const isWorkbenchHome = computed(() => String(route.name || '') === 'workbench-home')
const isUnifiedRepo = computed(() => {
  if (String(route.name || '') !== 'workbench-unified') return false
  const f = String(route.query.focus || '').trim().toLowerCase()
  return f === 'repository' || f === ''
})
const scriptWorkflowsNavActive = computed(() => String(route.path || '').includes('/script-workflows'))
const myEmployeesNavActive = computed(() => String(route.name || '') === 'workbench-employees')
const isMaterialsPage = computed(() => String(route.name || '') === 'workbench-materials')
const isChatTab = computed(() => String(route.name || '') === 'workbench-home')
const isEmployeeTab = computed(() => String(route.name || '') === 'workbench-employees')
const isMyTab = computed(() => String(route.name || '') === 'workbench-materials')
const isPageScrollRoute = computed(() => {
  const n = String(route.name || '')
  return (
    n === 'workbench-download' ||
    n === 'workbench-employees' ||
    n === 'workbench-materials' ||
    n === 'workbench-script-workflows' ||
    n === 'workbench-script-workflow-detail' ||
    n === 'workbench-script-workflow-new' ||
    n === 'workbench-script-workflow-edit' ||
    n === 'workbench-change-requests'
  )
})

async function navigateTo(routeLocation: Parameters<typeof router.push>[0]) {
  try {
    await router.push(routeLocation)
  } catch (err) {
    const msg = String((err as Error)?.message || err || '')
    if (msg.includes('Avoided redundant navigation')) return
    try {
      const resolved = router.resolve(routeLocation)
      window.location.assign(resolved.href)
    } catch {
      /* ignore */
    }
  }
}
</script>

<style scoped>
.workbench {
  display: flex;
  flex-direction: column;
  flex: 1 1 0%;
  height: 100%;
  min-height: 0;
  width: 100%;
  min-width: 0;
  background: #0a0a0a;
}

.wb-scene-nav {
  display: flex;
  flex-direction: row;
  gap: 2px;
  padding: 0.5rem;
  flex-shrink: 0;
}

.wb-scene-nav-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  border-radius: 8px;
  color: rgba(240, 240, 245, 0.4);
  text-decoration: none;
  font-size: 12px;
  font-weight: 500;
  transition: all 180ms cubic-bezier(0.4, 0, 0.2, 1);
  white-space: nowrap;
}

.wb-scene-nav-item:hover {
  background: rgba(129, 140, 248, 0.08);
  color: rgba(240, 240, 245, 0.7);
}

.wb-scene-nav-item--active {
  background: rgba(129, 140, 248, 0.12);
  color: rgba(240, 240, 245, 0.95);
}

.wb-scene-nav-item--soon {
  opacity: 0.4;
  cursor: default;
  pointer-events: none;
}

.wb-scene-nav-brand {
  margin-left: auto;
  font-size: 14px;
  font-weight: 800;
  letter-spacing: -0.5px;
  background: linear-gradient(135deg, #1e3a5f 0%, #6366f1 50%, #0a0a0a 100%);
  color: transparent;
  background-clip: text;
  -webkit-background-clip: text;
  user-select: none;
  pointer-events: none;
}

.workbench-main {
  flex: 1 1 auto;
  min-width: 0;
  min-height: 0;
}

.workbench-main--page-scroll {
  overflow-y: auto;
  overscroll-behavior: contain;
  -webkit-overflow-scrolling: touch;
}

html[data-workbench-theme='light'] .workbench{background:#f5f5f7}
html[data-workbench-theme='light'] .wb-scene-nav-item{color:#86868b}
html[data-workbench-theme='light'] .wb-scene-nav-item:hover{background:rgba(0,0,0,.04);color:#1d1d1f}
html[data-workbench-theme='light'] .wb-scene-nav-item--active{background:rgba(0,113,227,.08);color:#1d1d1f}
html[data-workbench-theme='light'] .wb-scene-nav-brand{background:linear-gradient(135deg,#0071e3 0%,#1d1d1f 100%);color:transparent;background-clip:text;-webkit-background-clip:text}
@media (max-width: 768px) {
  html[data-workbench-theme='light'] .wb-scene-nav {
    border-bottom-color: rgba(0, 0, 0, 0.08);
  }
}

.wb-mobile-tabbar {
  display: none;
}

@media (max-width: 768px) {
  .workbench--home .wb-scene-nav {
    display: none;
  }

  .wb-scene-nav {
    display: flex;
    overflow-x: auto;
    overflow-y: hidden;
    -webkit-overflow-scrolling: touch;
    scrollbar-width: none;
    gap: 4px;
    padding: 0.35rem 0.5rem;
    padding-left: max(3rem, env(safe-area-inset-left));
    padding-right: max(0.5rem, env(safe-area-inset-right));
    border-bottom: 1px solid rgba(255, 255, 255, 0.06);
  }

  .wb-scene-nav::-webkit-scrollbar {
    display: none;
  }

  .wb-scene-nav-brand {
    display: none;
  }

  .wb-scene-nav-item {
    flex-shrink: 0;
    font-size: 11px;
    padding: 5px 9px;
  }

  .wb-mobile-tabbar {
    display: flex;
    flex-direction: row;
    align-items: center;
    justify-content: space-around;
    position: fixed;
    bottom: 0;
    left: 0;
    right: 0;
    height: 56px;
    padding-bottom: env(safe-area-inset-bottom);
    background: rgba(10, 10, 10, 0.95);
    backdrop-filter: blur(20px);
    -webkit-backdrop-filter: blur(20px);
    border-top: 1px solid rgba(255, 255, 255, 0.06);
    z-index: 200;
  }
  .wb-mobile-tabbar-item {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 2px;
    flex: 1;
    min-width: 0;
    padding: 4px 0;
    color: rgba(240, 240, 245, 0.35);
    text-decoration: none;
    font-size: 9px;
    font-weight: 500;
    cursor: pointer;
    -webkit-tap-highlight-color: transparent;
    transition: color 150ms ease;
  }
  .wb-mobile-tabbar-item svg {
    flex-shrink: 0;
  }
  .wb-mobile-tabbar-item span {
    max-width: 100%;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .wb-mobile-tabbar-item--active {
    color: rgba(240, 240, 245, 0.95);
  }
  .workbench-main {
    padding-bottom: calc(56px + env(safe-area-inset-bottom));
  }
}

html[data-workbench-theme='light'] .wb-mobile-tabbar {
  background: rgba(245, 245, 247, 0.95);
  border-top-color: rgba(0, 0, 0, 0.08);
}
html[data-workbench-theme='light'] .wb-mobile-tabbar-item {
  color: #86868b;
}
html[data-workbench-theme='light'] .wb-mobile-tabbar-item--active {
  color: #1d1d1f;
}
</style>
