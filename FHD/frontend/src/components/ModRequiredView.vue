<template>
  <div class="page-view mod-required-view">
    <div class="page-content">
      <div class="card" style="max-width: 560px; margin: 48px auto; padding: 24px">
        <h2 style="margin: 0 0 12px">{{ title || '功能未启用' }}</h2>
        <p class="muted" style="margin: 0 0 16px; line-height: 1.6">
          本机尚未安装 Mod <code>{{ modId }}</code
          >，部分能力可能不可用。 可在「智能生态 → AI 市场 → {{ marketType === 'module' ? '模块' : '员工' }}」安装对应扩展，或联系管理员将 Mod 部署到 <code>FHD/mods/</code> 后刷新。
        </p>
        <div class="mod-required-actions">
          <router-link class="btn btn-primary btn-sm" :to="{ name: 'mod-store', query: { type: marketType } }">打开 AI 市场</router-link>
          <router-link class="btn btn-secondary btn-sm" :to="{ name: 'chat' }">返回智能对话</router-link>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { catalogStoreCollection, isEmployeePackListingModId, STORE_COLLECTION_INDUSTRY_MOD } from '@/constants/genericModPack'

const props = defineProps<{
  modId: string
  title?: string
}>()

const marketType = computed(() => !isEmployeePackListingModId(props.modId) && catalogStoreCollection({ id: props.modId }) === STORE_COLLECTION_INDUSTRY_MOD ? 'module' : 'employee')
</script>

<style scoped>
.mod-required-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
</style>
