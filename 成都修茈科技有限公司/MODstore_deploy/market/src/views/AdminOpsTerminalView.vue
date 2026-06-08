<script setup lang="ts">
import { computed } from 'vue'
import { storeToRefs } from 'pinia'
import { useAuthStore } from '../stores/auth'
import { xcagiAibizDashboardUrl } from '../constants/xcagiDashboardEmbed'

const authStore = useAuthStore()
const { isAdmin } = storeToRefs(authStore)

const iframeSrc = computed(() => xcagiAibizDashboardUrl())
</script>

<template>
  <div v-if="!isAdmin" class="ops-terminal-denied">
    <p>需要管理员权限。</p>
  </div>
  <div v-else class="ops-terminal-view" id="view-admin-ops-terminal">
    <div class="page-header">
      <div>
        <h2>运维终端</h2>
        <p class="page-desc">AI 业务数据 · 与全景仪表盘 #aibiz 同源（Web / 桌面 / App 终端 + Prometheus）</p>
      </div>
    </div>
    <iframe
      class="ops-terminal-frame"
      :src="iframeSrc"
      title="AI 业务数据 · 运维终端"
      referrerpolicy="no-referrer"
    />
  </div>
</template>

<style scoped>
.ops-terminal-denied {
  padding: 24px;
  color: #94a3b8;
}

.ops-terminal-view {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: min(88vh, 960px);
  padding: 16px 20px 20px;
  box-sizing: border-box;
}

.page-header {
  margin-bottom: 12px;
}

.page-header h2 {
  margin: 0 0 4px;
  font-size: 1.25rem;
}

.page-desc {
  margin: 0;
  font-size: 0.85rem;
  color: #64748b;
}

.ops-terminal-frame {
  flex: 1;
  width: 100%;
  min-height: 640px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #0f172a;
}
</style>
