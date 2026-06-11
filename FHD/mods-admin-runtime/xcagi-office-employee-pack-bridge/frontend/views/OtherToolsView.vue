<template>
  <div class="page-view" id="view-other-tools">
    <div class="page-content">
      <div class="page-header">
        <h2>员工视图</h2>
        <p class="employee-view-intro">
          在此直接启用/关闭工作流 AI 员工；开关与副窗「一键托管」同步。
        </p>
      </div>
      <WorkflowEmployeeSelectPanel />
      <div v-if="showModStoreEntry" class="other-tools-card-actions">
        <router-link
          :to="{ name: 'mod-store', query: { redirect: '/other-tools' } }"
          class="btn btn-secondary"
          title="安装工作流员工 Mod"
        >
          前往员工商店
        </router-link>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import WorkflowEmployeeSelectPanel from '@/components/workflow/WorkflowEmployeeSelectPanel.vue'
import { useWorkflowModsRuntimeContext } from '@/composables/useWorkflowModsRuntimeContext'
import { useModsStore } from '@/stores/mods'
import { onMounted } from 'vue'

const modsStore = useModsStore()
const { ctx, modWorkflowEmployeesActive } = useWorkflowModsRuntimeContext()

onMounted(async () => {
  if (modsStore.clientModsUiOff) return
  await modsStore.initialize(true)
})

const showModStoreEntry = computed(
  () =>
    !ctx.value.clientModsUiOff &&
    !ctx.value.modsDisabledByServer &&
    ctx.value.isModsListLoaded &&
    !modWorkflowEmployeesActive.value,
)
</script>

<style scoped>
.employee-view-intro {
  margin: 0 0 12px;
  color: #6b7280;
  font-size: 13px;
  line-height: 1.45;
}
.other-tools-card-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
}
</style>
