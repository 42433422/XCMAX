<template>
  <div class="unified-workbench">
    <header class="unified-toolbar">
      <div class="mode-tabs mode-tabs--desktop" role="tablist" aria-label="统一工作台视图">
        <button
          v-for="tab in modeTabs"
          :key="tab.mode"
          type="button"
          role="tab"
          class="mode-tab"
          :class="{ 'mode-tab--active': viewMode === tab.mode }"
          :aria-selected="viewMode === tab.mode"
          @click="setViewMode(tab.mode)"
        >
          {{ tab.label }}
        </button>
      </div>
      <label class="mode-tabs-mobile" aria-label="当前视图">
        <span class="mode-tabs-mobile-label">当前视图</span>
        <select
          class="mode-tabs-mobile-select input"
          :value="viewMode"
          @change="onMobileViewChange"
        >
          <option v-for="tab in modeTabs" :key="'m-' + tab.mode" :value="tab.mode">
            {{ tab.shortLabel }}
          </option>
        </select>
      </label>
    </header>

    <section class="focus-layout">
      <EmployeePanel v-if="viewMode === 'employee'" class="focus-embed" />
      <WorkflowPanel v-else-if="viewMode === 'workflow'" />
      <OpenApiConnectorsPanel v-else-if="viewMode === 'integrations'" />
      <VibeCodeSkillPanel v-else-if="viewMode === 'code_skill'" />
      <RepositoryPanel v-else />
    </section>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useWorkbenchSidebarStore } from '../stores/workbenchSidebar'
import EmployeePanel from '../components/workbench/EmployeePanel.vue'
import OpenApiConnectorsPanel from '../components/workbench/OpenApiConnectorsPanel.vue'
import RepositoryPanel from '../components/workbench/RepositoryPanel.vue'
import WorkflowPanel from '../components/workbench/WorkflowPanel.vue'
import VibeCodeSkillPanel from '../components/workbench/VibeCodeSkillPanel.vue'

const route = useRoute()
const router = useRouter()
const wbSidebar = useWorkbenchSidebarStore()

const allowed = new Set(['employee', 'workflow', 'skill', 'repository', 'integrations', 'code_skill'])

const modeTabs = [
  { mode: 'employee' as const, label: '专注员工制作', shortLabel: '员工制作' },
  { mode: 'workflow' as const, label: '专注 Skill 组', shortLabel: 'Skill 组' },
  { mode: 'code_skill' as const, label: 'AI 代码技能 (vibe)', shortLabel: '代码技能' },
  { mode: 'repository' as const, label: '专注 Mod 库', shortLabel: 'Mod 库' },
  { mode: 'integrations' as const, label: 'API 连接器', shortLabel: 'API 连接器' },
]

const routeFocus = computed(() => {
  const raw = String(route.query.focus || '').trim().toLowerCase()
  if (raw === 'hybrid') return 'employee'
  if (raw === 'skill') return 'workflow'
  return allowed.has(raw) ? raw : 'repository'
})

const viewMode = ref(routeFocus.value)

watch(
  () => route.query.focus,
  (focus) => {
    const f = String(focus || '').trim().toLowerCase()
    if (f === 'hybrid') {
      void router.replace({ name: 'workbench-unified', query: { ...route.query, focus: 'employee' } })
      return
    }
    if (f === 'workflow') {
      void router.replace({ name: 'workbench-unified', query: { ...route.query, focus: 'skill' } })
      return
    }
    viewMode.value = routeFocus.value
  },
  { immediate: true },
)

watch(routeFocus, (v) => {
  viewMode.value = v
})

function setViewMode(mode: string) {
  if (!allowed.has(mode)) return
  const query: Record<string, string | string[]> = { ...route.query } as Record<string, string | string[]>
  query.focus = mode === 'workflow' ? 'skill' : mode
  void router.replace({ name: 'workbench-unified', query })
}

function onMobileViewChange(ev: Event) {
  const sel = ev.target as HTMLSelectElement | null
  const mode = String(sel?.value || '').trim()
  if (mode) setViewMode(mode)
}

/** 管理类统一工作台：桌面端默认折叠聊天侧栏，留出能力货架/编排视图宽度 */
function applyManagementSidebarDefault() {
  if (typeof window === 'undefined') return
  if (window.matchMedia('(max-width: 768px)').matches) {
    wbSidebar.closeMobile()
    return
  }
  try {
    if (localStorage.getItem('wb_sidebar_keep_expanded') === '1') return
  } catch {
    /* ignore */
  }
  wbSidebar.sidebarCollapsed = true
}

onMounted(() => {
  applyManagementSidebarDefault()
})

watch(
  () => wbSidebar.sidebarCollapsed,
  (collapsed) => {
    if (typeof window === 'undefined' || window.matchMedia('(max-width: 768px)').matches) return
    try {
      if (!collapsed) localStorage.setItem('wb_sidebar_keep_expanded', '1')
    } catch {
      /* ignore */
    }
  },
)
</script>

<style scoped>
.unified-workbench {
  display: flex;
  flex-direction: column;
  min-height: 0;
  height: 100%;
  background: #050505;
}

.unified-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.6rem 1rem;
  padding: 0.35rem 0.5rem;
}

.mode-tabs {
  display: flex;
  flex-wrap: nowrap;
  gap: 2px;
  max-width: 100%;
  overflow-x: auto;
  overflow-y: hidden;
  -webkit-overflow-scrolling: touch;
  scrollbar-width: thin;
  padding-bottom: 2px;
}

.mode-tabs-mobile {
  display: none;
  align-items: center;
  gap: 0.5rem;
  flex: 1 1 auto;
  min-width: 0;
}

.mode-tabs-mobile-label {
  font-size: 12px;
  color: rgba(240, 240, 245, 0.45);
  white-space: nowrap;
}

.mode-tabs-mobile-select {
  flex: 1 1 auto;
  min-width: 0;
  min-height: 36px;
  font-size: 13px;
}

.mode-tab {
  border: none;
  border-radius: 8px;
  background: transparent;
  color: rgba(240, 240, 245, 0.4);
  padding: 5px 10px;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: all 180ms cubic-bezier(0.4, 0, 0.2, 1);
  white-space: nowrap;
  flex-shrink: 0;
}

.mode-tab:hover {
  background: rgba(129, 140, 248, 0.08);
  color: rgba(240, 240, 245, 0.7);
}

.mode-tab--active {
  background: rgba(129, 140, 248, 0.12);
  color: rgba(240, 240, 245, 0.95);
  border: none;
  box-shadow: none;
}

.focus-layout {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.focus-embed {
  flex: 1 1 auto;
  min-height: 0;
  min-width: 0;
  overflow: auto;
}

@media (max-width: 768px) {
  .mode-tabs--desktop {
    display: none;
  }

  .mode-tabs-mobile {
    display: flex;
  }

  .unified-toolbar {
    padding-left: 2.75rem;
  }
}

@media (min-width: 769px) {
  .mode-tabs-mobile {
    display: none;
  }
}

html[data-workbench-theme='light'] .unified-workbench {
  background: #f5f5f7;
}

html[data-workbench-theme='light'] .mode-tab {
  color: #86868b;
}

html[data-workbench-theme='light'] .mode-tab:hover {
  background: rgba(0, 0, 0, 0.04);
  color: #1d1d1f;
}

html[data-workbench-theme='light'] .mode-tab--active {
  background: rgba(0, 113, 227, 0.08);
  color: #1d1d1f;
}

html[data-workbench-theme='light'] .mode-tabs-mobile-label {
  color: #86868b;
}
</style>
