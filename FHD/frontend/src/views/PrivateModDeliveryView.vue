<template>
  <div class="private-mod-delivery-page page-view active">
    <header class="private-mod-delivery-page__header">
      <button type="button" class="private-mod-delivery-page__back" @click="goBack">返回 AI 生态</button>
      <div>
        <div class="private-mod-delivery-page__eyebrow">生产员工</div>
        <h1>客户私有 Mod 生产中心</h1>
      </div>
    </header>
    <PrivateModDeliveryPanel />
  </div>
</template>

<script setup lang="ts">
import { useRouter } from 'vue-router'
import PrivateModDeliveryPanel from '@/components/privateMod/PrivateModDeliveryPanel.vue'
import { resolvePlannerPageRedirectForRouteName } from '@/utils/plannerPagePaths'

const router = useRouter()

function goBack() {
  const modPath = resolvePlannerPageRedirectForRouteName('ai-ecosystem')
  if (modPath) {
    router.push({ path: modPath })
    return
  }
  router.push({ name: 'ai-ecosystem' })
}
</script>

<style scoped>
.private-mod-delivery-page {
  height: 100%;
  overflow: auto;
  background: #f8fafc;
}
.private-mod-delivery-page__header {
  display: flex;
  align-items: flex-start;
  gap: 16px;
  width: min(1180px, 100%);
  margin: 0 auto;
  padding: 20px 24px 0;
  box-sizing: border-box;
}
.private-mod-delivery-page__back {
  border: 1px solid #cbd5e1;
  border-radius: 9px;
  padding: 8px 12px;
  background: #fff;
  color: #334155;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
}
.private-mod-delivery-page__eyebrow {
  color: #d97706;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
.private-mod-delivery-page__header h1 {
  margin: 4px 0 0;
  color: #172554;
  font-size: 22px;
  font-weight: 700;
}
</style>
