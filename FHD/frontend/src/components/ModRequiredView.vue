<template>
  <div class="page-view mod-required-view">
    <div class="page-content">
      <div class="card" style="max-width: 560px; margin: 48px auto; padding: 24px">
        <h2 style="margin: 0 0 12px">{{ builtIn ? '系统组件暂不可用' : title || '功能未启用' }}</h2>
        <p v-if="builtIn" class="muted" style="margin: 0 0 16px; line-height: 1.6">
          内置业务组件未能正确加载。请重新加载应用；如果问题持续出现，请联系管理员检查当前版本完整性。
        </p>
        <p v-else class="muted" style="margin: 0 0 16px; line-height: 1.6">
          当前版本尚未启用此扩展能力。可前往「智能生态 → 员工商店」查看，或联系管理员为当前组织启用。
        </p>
        <div class="mod-required-actions">
          <button v-if="builtIn" class="btn btn-primary btn-sm" type="button" @click="reloadApp">重新加载</button>
          <router-link v-else class="btn btn-primary btn-sm" :to="{ name: 'mod-store' }">打开员工商店</router-link>
          <router-link class="btn btn-secondary btn-sm" :to="{ name: 'chat' }">返回智能对话</router-link>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  modId: string
  title?: string
}>()

const BUILT_IN_MOD_IDS = new Set(['xcagi-erp-domain-bridge', 'xcagi-approval-bridge'])
const builtIn = computed(() => BUILT_IN_MOD_IDS.has(props.modId))

function reloadApp() {
  window.location.reload()
}
</script>

<style scoped>
.mod-required-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
</style>
