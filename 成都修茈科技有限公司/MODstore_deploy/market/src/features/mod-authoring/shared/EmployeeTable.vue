<script setup lang="ts">
import { useModAuthoringContext } from '../composables/useModAuthoringContext'

withDefaults(
  defineProps<{
    mode?: 'wizard' | 'expert'
  }>(),
  { mode: 'wizard' },
)

const emit = defineEmits<{
  'open-expert-files': []
}>()

const {
  workflowEmployeesRows,
  openEmployeePickModal,
  openEmployeeModal,
  confirmDeleteEmployee,
  registerWorkflowEmployeeCatalog,
  registerCatalogBusy,
  goEmployeePrefill,
  openWorkflowSandboxDecompose,
  linkableWorkflows,
  linkPick,
  linkWorkflowBusy,
  applyWorkflowLinkToRow,
} = useModAuthoringContext()

function goExpertFiles() {
  emit('open-expert-files')
}
</script>

<template>
  <div>
    <div class="emp-head-row">
      <h3 class="sub-title">员工</h3>
      <button v-if="mode === 'wizard'" type="button" class="linkish btn-ghost-inline" @click="goExpertFiles">
        编辑文件
      </button>
      <button v-if="mode === 'expert'" type="button" class="btn btn-primary btn-sm" @click="openEmployeePickModal">
        添加
      </button>
    </div>
    <p v-if="!workflowEmployeesRows.length" class="muted small emp-empty">
      暂无员工。请点上方「从 AI 市场选择」或「从本地添加」。
    </p>
    <div v-else class="emp-table-wrap">
      <table class="emp-table">
        <thead>
          <tr>
            <th>名称</th>
            <th v-if="mode === 'expert'">ID</th>
            <th v-if="mode === 'expert'" class="emp-th-link">工作流</th>
            <th>状态</th>
            <th class="emp-th-actions">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in workflowEmployeesRows" :key="'emp-' + row.index">
            <td>{{ row.label || row.title || '—' }}</td>
            <td v-if="mode === 'expert'" class="mono">{{ row.id || '—' }}</td>
            <td v-if="mode === 'expert'" class="emp-link-cell">
              <template v-if="row.linkedWorkflowId">
                <span class="muted small">#{{ row.linkedWorkflowId }}</span>
              </template>
              <div v-else class="wf-link-inline">
                <select
                  class="input input-sm wf-link-select"
                  :value="linkPick[row.index] ?? 0"
                  :disabled="linkWorkflowBusy || !linkableWorkflows.length"
                  @change="(ev) => { linkPick[row.index] = Number((ev.target as HTMLSelectElement).value) }"
                >
                  <option :value="0">选择…</option>
                  <option v-for="w in linkableWorkflows" :key="w.id" :value="w.id">{{ w.name }}</option>
                </select>
                <button
                  type="button"
                  class="btn btn-sm"
                  :disabled="linkWorkflowBusy || !linkPick[row.index]"
                  @click="applyWorkflowLinkToRow(row)"
                >
                  关联
                </button>
              </div>
            </td>
            <td class="emp-ready-cell">
              <span :class="['readiness-chip', row.ready ? 'readiness-chip-ok' : 'readiness-chip-warn']">
                {{ row.ready ? '就绪' : '待补' }}
              </span>
            </td>
            <td class="emp-actions-cell">
              <button type="button" class="btn btn-sm btn-ghost" @click="openEmployeeModal('edit', row.index)">编辑</button>
              <template v-if="mode === 'expert'">
                <button type="button" class="btn btn-sm btn-ghost" @click="goEmployeePrefill(row)">制作页</button>
                <button
                  type="button"
                  class="btn btn-sm"
                  :disabled="registerCatalogBusy === row.index"
                  @click="registerWorkflowEmployeeCatalog(row)"
                >
                  {{ registerCatalogBusy === row.index ? '…' : '登记' }}
                </button>
                <button
                  v-if="row.linkedWorkflowId"
                  type="button"
                  class="btn btn-sm btn-ghost"
                  @click="openWorkflowSandboxDecompose(row)"
                >
                  沙盒
                </button>
              </template>
              <button type="button" class="btn btn-sm btn-ghost danger" @click="confirmDeleteEmployee(row.index)">删</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
