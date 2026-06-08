<script setup lang="ts">
import { useRouter } from 'vue-router'
import EmployeeReadinessBar from '../shared/EmployeeReadinessBar.vue'
import EmployeeTable from '../shared/EmployeeTable.vue'
import { useModAuthoringContext } from '../composables/useModAuthoringContext'
import { MOD_AUTHORING_ATTACH_KEY } from '../types'

defineEmits<{
  'open-expert-files': []
}>()

const router = useRouter()
const { modId, openEmployeePickModal } = useModAuthoringContext()

function goAiStoreForAttach() {
  const id = modId.value
  if (!id) return
  try {
    sessionStorage.setItem(MOD_AUTHORING_ATTACH_KEY, JSON.stringify({ modId: id, step: 2 }))
  } catch {
    /* ignore */
  }
  router.push({ name: 'ai-store', query: { attachModId: id } })
}
</script>

<template>
  <section class="panel wizard-panel">
    <h2 class="panel-title">员工</h2>
    <div class="wizard-emp-actions">
      <button type="button" class="btn btn-primary btn-sm" @click="goAiStoreForAttach">从 AI 市场选择</button>
      <button type="button" class="btn btn-sm" @click="() => void openEmployeePickModal()">从本地添加</button>
    </div>
    <EmployeeReadinessBar mode="wizard" />
    <EmployeeTable mode="wizard" @open-expert-files="$emit('open-expert-files')" />
  </section>
</template>
