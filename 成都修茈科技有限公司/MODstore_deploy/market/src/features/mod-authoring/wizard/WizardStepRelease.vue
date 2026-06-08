<script setup lang="ts">
import ModChecklist from '../shared/ModChecklist.vue'
import EmployeeReadinessBar from '../shared/EmployeeReadinessBar.vue'
import { useModAuthoringContext } from '../composables/useModAuthoringContext'

const { modData, goRepo } = useModAuthoringContext()

const emit = defineEmits<{
  'open-expert': [tabId?: string]
}>()

function goSync() {
  emit('open-expert', 'snapshots')
}
</script>

<template>
  <section class="panel wizard-panel">
    <h2 class="panel-title">发布</h2>
    <p v-if="modData?.validation_ok" class="ok-line">校验通过</p>
    <p v-else class="warn-block">校验未通过，请在专家模式改配置</p>
    <ModChecklist />
    <EmployeeReadinessBar mode="wizard" />
    <div class="wizard-finish-actions">
      <button type="button" class="btn btn-primary" @click="goSync">版本</button>
      <button type="button" class="btn" @click="goRepo">回仓库</button>
      <button type="button" class="btn btn-ghost" @click="emit('open-expert')">专家模式</button>
    </div>
  </section>
</template>
