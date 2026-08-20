<script setup lang="ts">
defineProps<{
  statusLabel: string
  loading: boolean
  error: string
  onRefresh: () => void
}>()
</script>

<template>
  <div>
    <div class="selp-head">
      <div>
        <p class="selp-kicker">自进化循环</p>
        <h3 class="selp-title">系统自动维护状态</h3>
        <p class="selp-desc">展示系统自动维护的真实运行情况。</p>
      </div>
      <div class="selp-state">
        <span class="selp-state-dot" aria-hidden="true" />
        <strong>{{ statusLabel }}</strong>
        <button type="button" class="selp-refresh" :disabled="loading" @click="onRefresh">
          {{ loading ? '刷新中' : '刷新' }}
        </button>
      </div>
    </div>

    <p v-if="error" class="selp-error">{{ error }}</p>
  </div>
</template>

<style scoped>
.selp-head {
  display: flex;
  justify-content: space-between;
  gap: 14px;
  align-items: flex-start;
}

.selp-kicker {
  margin: 0 0 4px;
  color: var(--selp-accent);
  font-size: 12px;
  font-weight: 900;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.selp-title {
  margin: 0 0 5px;
  color: var(--selp-text);
  font-size: 18px;
  font-weight: 900;
}

.selp-desc {
  margin: 0;
  color: var(--selp-muted);
  font-size: 13px;
  line-height: 1.5;
}

.selp-state {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: flex-end;
  color: var(--selp-accent);
  font-size: 13px;
}

.selp-state-dot {
  width: 10px;
  height: 10px;
  border-radius: 999px;
  background: var(--selp-accent);
  box-shadow: 0 0 0 5px color-mix(in srgb, var(--selp-accent) 16%, transparent);
}

.selp-refresh {
  border: 1px solid color-mix(in srgb, var(--selp-accent) 25%, #dbe3ef);
  border-radius: 999px;
  background: #fff;
  color: var(--selp-accent);
  padding: 5px 10px;
  font-size: 12px;
  font-weight: 800;
  cursor: pointer;
}

.selp-refresh:disabled {
  opacity: 0.6;
  cursor: default;
}

.selp-error {
  margin: 0;
  border-radius: 10px;
  background: #fef2f2;
  color: #b91c1c;
  padding: 9px 11px;
  font-size: 12px;
}

@media (max-width: 640px) {
  .selp-head {
    flex-direction: column;
  }
}
</style>
