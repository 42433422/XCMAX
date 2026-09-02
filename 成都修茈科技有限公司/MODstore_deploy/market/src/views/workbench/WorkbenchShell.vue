<template>
  <div class="wb-shell" :class="{ 'wb-shell--embedded': embedded }">
    <!-- Top bar -->
    <header v-if="!embedded" class="wb-topbar">
      <!-- Left: branding + target tabs -->
      <div class="wb-topbar-left">
        <RouterLink
          class="wb-logo wb-logo-home-link"
          :to="{ name: 'workbench-home' }"
          title="返回工作台首页（三档对话）"
          aria-label="返回工作台首页（三档对话）"
        >
          <span class="wb-logo-return" aria-hidden="true">←</span>
          XCAGI <span class="wb-logo-badge">工作台</span>
        </RouterLink>
        <nav class="wb-target-tabs">
          <button
            v-for="tab in TARGET_TABS"
            :key="tab.kind"
            class="wb-target-tab"
            :class="{ 'wb-target-tab--active': store.target.kind === tab.kind }"
            @click="switchTarget(tab.kind)"
          >
            <span>{{ tab.icon }}</span>
            <span>{{ tab.label }}</span>
          </button>
        </nav>
      </div>

      <!-- Center: current target name + dirty indicator -->
      <div class="wb-topbar-center">
        <span class="wb-target-name">{{ store.target.name || '未命名' }}</span>
        <span v-if="store.dirty" class="wb-dirty">● 未保存</span>
        <span v-if="store.target.id" class="wb-target-id">ID: {{ store.target.id }}</span>
      </div>

      <!-- Right: action buttons -->
      <div class="wb-topbar-right">
        <span v-if="saveMsg" class="wb-save-msg" :class="{ 'wb-save-msg--ok': saveMsg.startsWith('配置') }">
          {{ saveMsg }}
        </span>
        <button class="wb-btn" @click="showPackagePanel = !showPackagePanel">上传打包</button>
        <button class="wb-btn" @click="showTestPanel = !showTestPanel">测试审核</button>
        <button class="wb-btn wb-btn--primary" :disabled="saving" @click="saveEmployee">
          {{ saving ? '保存中…' : '保存' }}
        </button>
        <button class="wb-btn wb-btn--publish" @click="showPublishPanel = !showPublishPanel">
          发布上架
        </button>
        <span class="wb-user">{{ auth.username || '—' }}</span>
      </div>
    </header>

    <!-- Loading / Error overlay -->
    <div v-if="loading" class="wb-loading">
      <span class="wb-loading-spinner">●</span> 加载中…
    </div>
    <div v-else-if="loadError" class="wb-error">加载失败：{{ loadError }}</div>

    <!-- Three-column body -->
    <div v-else class="wb-body" :class="{ 'wb-body--canvas-focus': sidePanelsCollapsed, 'wb-body--mobile': isMobile }">
      <!-- Left rail -->
      <div v-show="!sidePanelsCollapsed && (!isMobile || mobilePanel === 'left')" class="wb-col wb-col--left" :style="isMobile ? {} : { width: leftWidth + 'px' }">
        <LeftRail @select-employee="onSelectEmployee" />
      </div>

      <!-- Resize handle left -->
      <div
        v-show="!sidePanelsCollapsed && !isMobile"
        class="wb-resize"
        @mousedown="onLeftResizeMouseDown"
      />

      <!-- Center canvas -->
      <div v-show="!isMobile || mobilePanel === 'canvas'" class="wb-col wb-col--center">
        <CanvasStage ref="canvasRef" @layout-mode-change="onCanvasLayoutModeChange" />
      </div>

      <!-- Resize handle right -->
      <div
        v-show="!sidePanelsCollapsed && !isMobile"
        class="wb-resize"
        @mousedown="onRightResizeMouseDown"
      />

      <!-- Right rail -->
      <div v-show="!sidePanelsCollapsed && (!isMobile || mobilePanel === 'right')" class="wb-col wb-col--right" :style="isMobile ? {} : { width: rightWidth + 'px' }">
        <RightRail />
      </div>
    </div>

    <!-- Mobile bottom tab bar -->
    <nav v-if="isMobile && !loading && !loadError" class="wb-mobile-tabbar">
      <button class="wb-mobile-tab" :class="{ 'wb-mobile-tab--active': mobilePanel === 'left' }" @click="mobilePanel = 'left'">
        <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" stroke-width="1.4"><rect x="2" y="2" width="5" height="14" rx="1.5"/><rect x="9" y="2" width="7" height="6" rx="1.5"/></svg>
        <span>员工</span>
      </button>
      <button class="wb-mobile-tab" :class="{ 'wb-mobile-tab--active': mobilePanel === 'canvas' }" @click="mobilePanel = 'canvas'">
        <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" stroke-width="1.4"><circle cx="9" cy="9" r="7"/><circle cx="9" cy="9" r="2.5" fill="currentColor" stroke="none"/></svg>
        <span>画布</span>
      </button>
      <button class="wb-mobile-tab" :class="{ 'wb-mobile-tab--active': mobilePanel === 'right' }" @click="mobilePanel = 'right'">
        <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" stroke-width="1.4"><rect x="2" y="10" width="7" height="6" rx="1.5"/><rect x="11" y="2" width="5" height="14" rx="1.5"/></svg>
        <span>配置</span>
      </button>
    </nav>

    <!-- Package panel drawer -->
    <transition name="drawer">
      <div v-if="showPackagePanel" class="wb-drawer">
        <div class="wb-drawer-header">
          <span>上传打包</span>
          <button class="wb-drawer-close" @click="showPackagePanel = false">✕</button>
        </div>
        <div class="wb-drawer-body">
          <pre class="drawer-json">{{ JSON.stringify(store.target.manifest, null, 2) }}</pre>
        </div>
      </div>
    </transition>

    <!-- Test panel drawer -->
    <transition name="drawer">
      <div v-if="showTestPanel" class="wb-drawer">
        <div class="wb-drawer-header">
          <span>测试审核</span>
          <button class="wb-drawer-close" @click="showTestPanel = false">✕</button>
        </div>
        <div class="wb-drawer-body">
          <p v-if="!store.target.id" class="drawer-warn">请先保存员工以获得 ID。</p>
        </div>
      </div>
    </transition>

    <!-- Publish panel drawer -->
    <transition name="drawer">
      <div v-if="showPublishPanel" class="wb-drawer">
        <div class="wb-drawer-header">
          <span>发布上架</span>
          <button class="wb-drawer-close" @click="showPublishPanel = false">✕</button>
        </div>
        <div class="wb-drawer-body">
          <p v-if="!store.target.id" class="drawer-warn">请先保存员工以获得 ID。</p>
        </div>
      </div>
    </transition>
  </div>
</template>

<script setup lang="ts">
// 拆分后本文件为组装入口（façade）：逻辑在 ./workbench-shell/，样式在 ./workbench-shell/workbench-shell.css。
import { useRoute, useRouter } from 'vue-router'
import LeftRail from './panels/LeftRail.vue'
import CanvasStage from './panels/CanvasStage.vue'
import RightRail from './panels/RightRail.vue'
import { useWorkbenchStore } from '../../stores/workbench'
import { useAuthStore } from '../../stores/auth'
import type { TargetKind } from '../../stores/workbench'
import { useBreakpoint } from '../../composables/useBreakpoint'
import { useWorkbenchShell } from './workbench-shell/useWorkbenchShell'

const store = useWorkbenchStore()
const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const { isMobile } = useBreakpoint()

const props = withDefaults(defineProps<{
  embedded?: boolean
  initialTarget?: TargetKind
}>(), {
  embedded: false,
  initialTarget: 'employee',
})

const {
  mobilePanel,
  canvasRef,
  loading,
  loadError,
  resolveKind,
  resolveId,
  normalizeEmployeePackManifest,
  buildEmptyEmployeeManifestForEditor,
  loadTarget,
  TARGET_TABS,
  switchTarget,
  leftWidth,
  rightWidth,
  sidePanelsCollapsed,
  onLeftResizeMouseDown,
  onRightResizeMouseDown,
  onCanvasLayoutModeChange,
  saving,
  saveMsg,
  saveEmployee,
  onSelectEmployee,
  showPackagePanel,
  showTestPanel,
  showPublishPanel,
} = useWorkbenchShell({ store, route, router, props })
</script>

<style scoped src="./workbench-shell/workbench-shell.css"></style>
