<template>
  <section class="kitten-viz-strip" aria-label="可视化 AI 员工">
    <div class="kitten-viz-strip__head">
      <div>
        <div class="kitten-viz-strip__title">可视化 AI 员工</div>
        <div class="kitten-viz-strip__subtitle">
          办公员工附属包2 · 已安装 {{ installedCount }}/{{ employees.length }}
          <span v-if="loading" class="kitten-viz-strip__loading">同步中…</span>
        </div>
      </div>
      <button type="button" class="kitten-viz-strip__market" @click="goMarket">
        去 AI 市场安装
      </button>
    </div>

    <div class="kitten-viz-strip__grid" role="list">
      <button
        v-for="emp in employees"
        :key="emp.pkgId"
        type="button"
        role="listitem"
        class="kitten-viz-card"
        :class="{
          'is-active': emp.pkgId === selectedPkgId,
          'is-locked': !emp.installed,
        }"
        :style="{ '--viz-accent': emp.palette[0] }"
        @click="onSelect(emp)"
      >
        <span class="kitten-viz-card__icon" aria-hidden="true">{{ emp.icon }}</span>
        <span class="kitten-viz-card__name">{{ emp.name }}</span>
        <span class="kitten-viz-card__desc">{{ emp.description }}</span>
        <span v-if="!emp.installed" class="kitten-viz-card__badge">未安装</span>
        <span v-else-if="emp.pkgId === selectedPkgId" class="kitten-viz-card__badge kitten-viz-card__badge--on">使用中</span>
      </button>
    </div>
  </section>
</template>

<script setup lang="ts">
import type { KittenVizEmployeeState } from '@/composables/useKittenVizEmployees'

const props = defineProps<{
  employees: KittenVizEmployeeState[]
  selectedPkgId: string
  installedCount: number
  loading?: boolean
}>()

const emit = defineEmits<{
  select: [pkgId: string]
}>()

function onSelect(emp: KittenVizEmployeeState) {
  if (!emp.installed) {
    goMarket()
    return
  }
  emit('select', emp.pkgId)
}

function goMarket() {
  const marketBase = String(import.meta.env.VITE_MARKET_BASE || 'https://xiu-ci.com/market').replace(/\/$/, '')
  const url = `${marketBase}/ai-store?nav=office_aux_2`
  window.open(url, '_blank', 'noopener,noreferrer')
}
</script>

<style scoped>
.kitten-viz-strip {
  margin: 0 16px 12px;
  padding: 14px 16px;
  border-radius: 14px;
  background: linear-gradient(135deg, #f8fafc 0%, #eef2ff 100%);
  border: 1px solid #e2e8f0;
}

.kitten-viz-strip__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.kitten-viz-strip__title {
  font-size: 15px;
  font-weight: 700;
  color: #1e293b;
}

.kitten-viz-strip__subtitle {
  margin-top: 4px;
  font-size: 12px;
  color: #64748b;
}

.kitten-viz-strip__loading {
  margin-left: 6px;
  color: #6366f1;
}

.kitten-viz-strip__market {
  flex-shrink: 0;
  padding: 6px 12px;
  border-radius: 999px;
  border: 1px solid #c7d2fe;
  background: #fff;
  color: #4338ca;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
}

.kitten-viz-strip__market:hover {
  background: #eef2ff;
}

.kitten-viz-strip__grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}

@media (max-width: 960px) {
  .kitten-viz-strip__grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

.kitten-viz-card {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
  padding: 12px;
  border-radius: 12px;
  border: 2px solid transparent;
  background: #fff;
  box-shadow: 0 4px 14px rgba(15, 23, 42, 0.05);
  text-align: left;
  cursor: pointer;
  transition: border-color 0.15s, transform 0.15s;
}

.kitten-viz-card:hover {
  transform: translateY(-1px);
}

.kitten-viz-card.is-active {
  border-color: var(--viz-accent, #6366f1);
  box-shadow: 0 8px 20px rgba(99, 102, 241, 0.12);
}

.kitten-viz-card.is-locked {
  opacity: 0.82;
}

.kitten-viz-card__icon {
  font-size: 22px;
  line-height: 1;
}

.kitten-viz-card__name {
  font-size: 13px;
  font-weight: 700;
  color: #0f172a;
}

.kitten-viz-card__desc {
  font-size: 11px;
  line-height: 1.45;
  color: #64748b;
}

.kitten-viz-card__badge {
  position: absolute;
  top: 8px;
  right: 8px;
  padding: 2px 7px;
  border-radius: 999px;
  font-size: 10px;
  font-weight: 600;
  background: #f1f5f9;
  color: #64748b;
}

.kitten-viz-card__badge--on {
  background: #dbeafe;
  color: #1d4ed8;
}
</style>
