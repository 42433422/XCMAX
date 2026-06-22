<template>
  <div
    class="industry-selector is-readonly"
    :title="readonlyTooltip"
    role="status"
    aria-live="polite"
  >
    <div class="selector-trigger" :aria-label="`当前行业：${currentIndustryName}`">
      <span class="industry-icon"><i class="fa fa-industry" aria-hidden="true"></i></span>
      <span class="industry-name">{{ currentIndustryName }}</span>
      <span class="industry-unit" v-if="primaryUnit">{{ primaryUnit }}</span>
      <span class="lock-icon" aria-hidden="true"><i class="fa fa-lock"></i></span>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted } from 'vue'
import { useIndustryStore } from '@/stores/industry'

const industryStore = useIndustryStore()

const readonlyTooltip = '行业由管理员设置，不可在此切换'

const currentIndustryName = computed(() => industryStore.currentIndustry?.name || '加载中...')
const primaryUnit = computed(() => industryStore.currentConfig?.units?.primary || '')

onMounted(async () => {
  if (!industryStore.isLoaded) {
    await industryStore.initialize()
  }
})
</script>

<style scoped>
.industry-selector {
  position: relative;
}

.industry-selector.is-readonly {
  cursor: not-allowed;
}

.selector-trigger {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 15px;
  user-select: none;
  color: rgba(255, 255, 255, 0.65);
  border-radius: 4px;
  margin: 2px 8px;
  opacity: 0.85;
}

.industry-icon {
  font-size: 14px;
}

.industry-name {
  font-weight: 500;
  flex: 1;
}

.industry-unit {
  font-size: 12px;
  padding: 2px 6px;
  background: rgba(79, 172, 254, 0.2);
  color: #4facfe;
  border-radius: 4px;
}

.lock-icon {
  font-size: 11px;
  color: rgba(255, 255, 255, 0.45);
}
</style>
