<script setup lang="ts">
// 拆分自 App.vue 模板（原第 40–164 行）；模板逐字迁移，事件改为 emits，行为不变。
import { storeToRefs } from 'pinia'
import { useRoute } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { useWalletStore } from '../stores/wallet'
import { useWorkbenchSidebarStore } from '../stores/workbenchSidebar'
import SidebarCustomerLinks from '../components/workbench/SidebarCustomerLinks.vue'
import SidebarUserMenu from '../components/workbench/SidebarUserMenu.vue'
import { formatConvTime } from './appShellTypes'

defineProps<{
  isAndroidEmbeddedShell: boolean
  isMobileViewport: boolean
  convSwipeOffset: Record<string, number>
}>()

defineEmits<{
  (e: 'new-chat'): void
  (e: 'pick-conversation', id: string): void
  (e: 'conv-touchstart', ev: TouchEvent, id: string): void
  (e: 'conv-touchmove', ev: TouchEvent, id: string): void
  (e: 'conv-touchend', id: string): void
  (e: 'conv-mousedown', ev: MouseEvent, id: string): void
  (e: 'remove-conversation', id: string): void
  (e: 'mode-click', mode: 'direct' | 'make' | 'voice'): void
  (e: 'settings'): void
  (e: 'admin-enter', routeName: string): void
  (e: 'logout'): void
  (e: 'back-client'): void
}>()

const route = useRoute()
const authStore = useAuthStore()
const walletStore = useWalletStore()
const wbSidebar = useWorkbenchSidebarStore()
const isTestMode = import.meta.env.MODE === 'test'
const { username, currentMode, levelProfile, isAdmin } = storeToRefs(authStore)
const { balance } = storeToRefs(walletStore)
</script>

<template>
  <aside
    v-if="!isAndroidEmbeddedShell"
    id="wb-sidebar"
    class="wb-sidebar"
    role="navigation"
    aria-label="工作台侧边栏"
    :class="{
      'wb-sidebar--collapsed': !isMobileViewport && wbSidebar.sidebarCollapsed,
      'wb-sidebar--mobile-open': wbSidebar.mobileOpen,
    }"
    :aria-hidden="isMobileViewport && !wbSidebar.mobileOpen ? 'true' : undefined"
    :inert="isMobileViewport && !wbSidebar.mobileOpen ? true : undefined"
  >
    <div class="wb-sidebar-top">
      <button
        type="button"
        class="wb-sidebar-toggle"
        :aria-label="isMobileViewport ? (wbSidebar.mobileOpen ? '关闭菜单' : '打开菜单') : (wbSidebar.sidebarCollapsed ? '展开侧边栏' : '折叠侧边栏')"
        @click="wbSidebar.toggleSidebar()"
      >
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4"><rect x="0.5" y="2" width="15" height="12" rx="1.5" fill="none"/><rect x="2" y="4" width="3.5" height="8" rx="0.5" fill="currentColor"/></svg>
      </button>
      <button v-if="currentMode !== 'admin'" type="button" class="wb-sidebar-new-chat" @click="$emit('new-chat')">
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><line x1="8" y1="2" x2="8" y2="14"/><line x1="2" y1="8" x2="14" y2="8"/></svg>
        <span>新对话</span>
      </button>
      <span v-else class="wb-sidebar-admin-label">管理端</span>
    </div>

    <div class="wb-sidebar-conv-list" v-if="currentMode !== 'admin'">
      <div v-for="conv in wbSidebar.conversations" :key="conv.id" class="wb-sidebar-conv-item-wrap">
        <div class="wb-sidebar-conv-item" :class="{ 'wb-sidebar-conv-item--active': conv.id === wbSidebar.activeConversationId }" :style="{ transform: convSwipeOffset[conv.id] ? `translateX(-${convSwipeOffset[conv.id]}px)` : '' }" @click="$emit('pick-conversation', conv.id)" @touchstart.passive="$emit('conv-touchstart', $event, conv.id)" @touchmove.passive="$emit('conv-touchmove', $event, conv.id)" @touchend="$emit('conv-touchend', conv.id)" @mousedown.prevent="$emit('conv-mousedown', $event, conv.id)">
          <span class="wb-sidebar-conv-title" :title="conv.title || '新对话'">{{ conv.title || '新对话' }}</span>
          <span class="wb-sidebar-conv-time">{{ formatConvTime(conv.updatedAt) }}</span>
        </div>
        <button type="button" class="wb-sidebar-conv-delete" :style="{ opacity: convSwipeOffset[conv.id] ? 1 : 0, pointerEvents: convSwipeOffset[conv.id] ? 'auto' : 'none' }" @click.stop="$emit('remove-conversation', conv.id)" aria-label="删除对话">
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"><path d="M2 4h10M5 4V2.5a.5.5 0 01.5-.5h3a.5.5 0 01.5.5V4M3.5 4v7.5a1 1 0 001 1h5a1 1 0 001-1V4"/></svg>
        </button>
      </div>
    </div>

    <div class="wb-sidebar-admin-nav" v-if="currentMode === 'admin' && !isTestMode">
      <div class="wb-sidebar-admin-nav-title">管理端</div>
      <router-link :to="{ name: 'admin-database' }" class="wb-sidebar-mode-btn" :class="{ 'wb-sidebar-mode-btn--active': route.name === 'admin-database' }">
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"><ellipse cx="8" cy="4" rx="5.5" ry="2.5"/><path d="M2.5 4v8c0 1.38 2.46 2.5 5.5 2.5s5.5-1.12 5.5-2.5V4"/><path d="M2.5 8c0 1.38 2.46 2.5 5.5 2.5s5.5-1.12 5.5-2.5"/></svg>
        <span>数据库管理</span>
      </router-link>
      <router-link :to="{ name: 'admin-duty-employees' }" class="wb-sidebar-mode-btn" :class="{ 'wb-sidebar-mode-btn--active': route.name === 'admin-duty-employees' }">
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"><circle cx="8" cy="4.5" r="2.5"/><path d="M3 14v-1a4 4 0 018 0v1"/><path d="M12 3l1.5 1.5M12 3l1.5-1.5"/></svg>
        <span>值班员工</span>
      </router-link>
      <router-link :to="{ name: 'admin-ops-audit' }" class="wb-sidebar-mode-btn" :class="{ 'wb-sidebar-mode-btn--active': route.name === 'admin-ops-audit' }">
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"><path d="M2 3h12v10H2z"/><path d="M5 7h6M5 10h4"/></svg>
        <span>运维审计</span>
      </router-link>
      <router-link :to="{ name: 'admin-employee-autonomy' }" class="wb-sidebar-mode-btn" :class="{ 'wb-sidebar-mode-btn--active': route.name === 'admin-employee-autonomy' }">
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"><path d="M8 1v2M8 13v2M1 8h2M13 8h2"/><circle cx="8" cy="8" r="3"/><path d="M3.05 3.05l1.41 1.41M11.54 11.54l1.41 1.41M3.05 12.95l1.41-1.41M11.54 4.46l1.41-1.41"/></svg>
        <span>员工自主决策</span>
      </router-link>
      <router-link :to="{ name: 'admin-change-requests' }" class="wb-sidebar-mode-btn" :class="{ 'wb-sidebar-mode-btn--active': route.name === 'admin-change-requests' }">
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"><path d="M2 4l3-2 3 2v4l-3 2-3-2V4z"/><path d="M8 4l3-2 3 2v4l-3 2-3-2V4z"/></svg>
        <span>变更请求</span>
      </router-link>
      <router-link :to="{ name: 'admin-yuangon-onboard' }" class="wb-sidebar-mode-btn" :class="{ 'wb-sidebar-mode-btn--active': route.name === 'admin-yuangon-onboard' }">
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"><path d="M8 1.5v4M8 10.5v4M1.5 8h4M10.5 8h4"/><circle cx="8" cy="8" r="2.5"/></svg>
        <span>员工入职</span>
      </router-link>
      <router-link :to="{ name: 'admin-orchestrate-jobs' }" class="wb-sidebar-mode-btn" :class="{ 'wb-sidebar-mode-btn--active': route.name === 'admin-orchestrate-jobs' }">
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"><path d="M1.5 2h5v5h-5z"/><path d="M9.5 2h5v5h-5z"/><path d="M1.5 9h5v5h-5z"/><path d="M9.5 9h5v5h-5z"/></svg>
        <span>编排任务</span>
      </router-link>
      <router-link :to="{ name: 'admin-customer-service' }" class="wb-sidebar-mode-btn" :class="{ 'wb-sidebar-mode-btn--active': route.name === 'admin-customer-service' }">
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7a5 5 0 0110 0v2a5 5 0 01-10 0V7z"/><path d="M1 10v1a2 2 0 004 0V9"/><path d="M11 9v2a2 2 0 004 0v-1"/><path d="M6 13a2 2 0 004 0"/></svg>
        <span>客服审核</span>
      </router-link>
      <router-link :to="{ name: 'admin-butler-skills' }" class="wb-sidebar-mode-btn" :class="{ 'wb-sidebar-mode-btn--active': route.name === 'admin-butler-skills' }">
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"><path d="M8 1l1.5 3.5L13 5.3l-2.5 2.4.6 3.3L8 9.3l-3.1 1.7.6-3.3L3 5.3l3.5-.8z"/></svg>
        <span>管家技能</span>
      </router-link>
      <router-link :to="{ name: 'admin-ai-accounts' }" class="wb-sidebar-mode-btn" :class="{ 'wb-sidebar-mode-btn--active': route.name === 'admin-ai-accounts' }">
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="2" width="12" height="12" rx="2"/><path d="M2 6h12"/><circle cx="5" cy="4" r="0.5" fill="currentColor"/><circle cx="8" cy="4" r="0.5" fill="currentColor"/></svg>
        <span>AI 账号池</span>
      </router-link>
    </div>

    <div class="wb-sidebar-divider"></div>

    <div class="wb-sidebar-modes" v-if="currentMode !== 'admin'">
      <button type="button" class="wb-sidebar-mode-btn" :class="{ 'wb-sidebar-mode-btn--active': wbSidebar.activeMode === 'direct' }" @click="$emit('mode-click', 'direct')">
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"><path d="M2 4h12M2 8h8M2 12h5"/></svg>
        <span>聊</span>
      </button>
      <button type="button" class="wb-sidebar-mode-btn" :class="{ 'wb-sidebar-mode-btn--active': wbSidebar.activeMode === 'make' }" @click="$emit('mode-click', 'make')">
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"><rect x="1.5" y="1.5" width="13" height="13" rx="2"/><path d="M8 5v6M5 8h6"/></svg>
        <span>做</span>
      </button>
      <button type="button" class="wb-sidebar-mode-btn" :class="{ 'wb-sidebar-mode-btn--active': wbSidebar.activeMode === 'voice' }" @click="$emit('mode-click', 'voice')">
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"><path d="M8 2v8"/><path d="M5 6a3 3 0 016 0v2a3 3 0 01-6 0V6z"/><path d="M2 10v1a6 6 0 0012 0v-1"/></svg>
        <span>说</span>
      </button>
    </div>

    <div class="wb-sidebar-bottom">
      <SidebarCustomerLinks
        v-if="currentMode !== 'admin'"
        :route-name="String(route.name || '')"
        @navigate="wbSidebar.closeMobile()"
      />
      <div class="wb-sidebar-divider" v-if="currentMode !== 'admin'"></div>
      <button v-if="currentMode === 'admin'" type="button" class="wb-sidebar-mode-btn wb-sidebar-back-btn" @click="$emit('back-client')">
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"><path d="M10 3L5 8l5 5"/></svg>
        <span>返回客户端</span>
      </button>
      <SidebarUserMenu
        v-if="currentMode !== 'admin'"
        :username="username || ''"
        :balance="balance"
        :level-profile="levelProfile"
        :is-admin="isAdmin"
        @settings="$emit('settings')"
        @admin="$emit('admin-enter', 'admin-database')"
        @logout="$emit('logout')"
      />
    </div>
  </aside>
</template>
