<template>
  <section v-if="visible" class="cs-funnel-bar">
    <button type="button" class="cs-funnel-toggle" @click="$emit('update:expanded', !expanded)">
      商机漏斗
      <span class="muted">（{{ funnelTotalClients }} 客户）</span>
      <i class="fa" :class="expanded ? 'fa-chevron-up' : 'fa-chevron-down'" aria-hidden="true" />
    </button>
    <div v-show="expanded" class="cs-funnel-body">
      <p v-if="funnelLoading" class="muted">加载漏斗…</p>
      <div v-else class="cs-funnel-stages">
        <button
          v-for="st in funnelStages"
          :key="st.id"
          type="button"
          class="cs-funnel-stage"
          :class="{ active: funnelStageFilter === st.id, 'has-count': st.count > 0 }"
          :title="st.label"
          @click="$emit('select-stage', st.id)"
        >
          <span class="cs-funnel-stage__count">{{ st.count }}</span>
          <span class="cs-funnel-stage__label">{{ st.label }}</span>
        </button>
      </div>
      <p v-if="funnelStageFilter" class="cs-funnel-filter-hint muted">
        已筛选阶段「{{ stageLabel(funnelStageFilter) }}」
        <button type="button" class="btn btn-xs btn-ghost" @click="$emit('clear-filter')">显示全部</button>
      </p>
    </div>
  </section>
</template>

<script setup lang="ts">
defineProps<{
  visible: boolean
  expanded: boolean
  funnelLoading: boolean
  funnelStages: Array<{ id: string; label: string; count: number }>
  funnelTotalClients: number
  funnelStageFilter: string
  stageLabel: (stageId: string) => string
}>()

defineEmits<{
  (e: 'update:expanded', value: boolean): void
  (e: 'select-stage', stageId: string): void
  (e: 'clear-filter'): void
}>()
</script>

<style scoped>
.cs-funnel-bar {
  margin: 0 0 12px; padding: 10px 12px; background: #fff; border: 1px solid #e8ecf2; border-radius: 10px;
}
.cs-funnel-toggle {
  display: flex; align-items: center; gap: 8px; width: 100%; border: none; background: transparent;
  font-size: 14px; font-weight: 600; color: #1e293b; cursor: pointer; padding: 0;
}
.cs-funnel-stages {
  display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px;
}
.cs-funnel-stage {
  display: flex; flex-direction: column; align-items: center; min-width: 72px; padding: 6px 8px;
  border: 1px solid #e2e8f0; border-radius: 8px; background: #f8fafc; cursor: pointer; font-size: 11px;
}
.cs-funnel-stage.active { border-color: #4a6cf7; background: #eff6ff; }
.cs-funnel-stage__count { font-size: 15px; font-weight: 700; color: #334155; }
.cs-funnel-stage__label { color: #64748b; margin-top: 2px; text-align: center; line-height: 1.2; }
.cs-funnel-filter-hint { margin: 8px 0 0; font-size: 12px; }
.muted { color: #94a3b8; }
.btn-xs { padding: 5px 12px; font-size: 12px; border-radius: 6px; border: 1px solid #e8ecf2; background: #fff; cursor: pointer; }
.btn-ghost { background: transparent; border: 1px solid #e8ecf2; color: #64748b; }
.btn-ghost:hover { border-color: #4a6cf7; color: #4a6cf7; }
</style>