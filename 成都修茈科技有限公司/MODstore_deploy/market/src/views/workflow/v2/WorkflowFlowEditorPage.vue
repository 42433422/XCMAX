<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import WorkflowFlowEditor from './WorkflowFlowEditor.vue'

const route = useRoute()
const router = useRouter()

const workflowId = computed(() => {
  const raw = route.params.id
  const v = Number(Array.isArray(raw) ? raw[0] : raw)
  return Number.isFinite(v) && v > 0 ? v : 0
})

function goBack() {
  router.push({ name: 'workflow' })
}
</script>

<template>
  <div class="wf2-page">
    <div v-if="!workflowId" class="wf2-page__error">
      <h2>工作流 ID 无效</h2>
      <button class="wf2-tb-btn" type="button" @click="goBack">返回工作流列表</button>
    </div>
    <WorkflowFlowEditor v-else :workflow-id="workflowId" @back="goBack" />
  </div>
</template>

<style scoped>
.wf2-page {
  height: 100vh;
  background: #0b1120;
}

.wf2-page__error {
  padding: 64px 24px;
  text-align: center;
  color: #94a3b8;
}

.wf2-tb-btn {
  margin-top: 16px;
  font-size: 13px;
  border: 1px solid rgba(148, 163, 184, 0.2);
  background: rgba(30, 41, 59, 0.6);
  color: #cbd5e1;
  padding: 6px 12px;
  border-radius: 6px;
  cursor: pointer;
}
</style>
