<template>
  <div class="approval-workspace-view">
    <div class="view-header">
      <h2>审批工作台</h2>
      <p class="subtitle">处理待审批事项，跟踪审批进度</p>
    </div>

    <AwEtlAutoIngestList />
    <AwStatsCards v-if="!fullListType" :tm="tm" />
    <nav v-else class="section-actions approval-list-pages" aria-label="完整审批列表">
      <button type="button" class="btn-link" @click="closeFullList">返回工作台</button>
      <strong>{{ fullListType === 'pending' ? '全部待我审批' : '全部我发起的审批' }}</strong>
      <button type="button" :disabled="fullListLoading || fullListPage <= 1" @click="loadFullListPage(fullListPage - 1)">上一页</button>
      <span>第 {{ fullListPage }} / {{ fullListPageCount }} 页</span>
      <button type="button" :disabled="fullListLoading || fullListPage >= fullListPageCount" @click="loadFullListPage(fullListPage + 1)">下一页</button>
    </nav>
    <p v-if="fullListLoading" role="status">正在读取审批列表…</p>
    <p v-else-if="fullListError" role="alert">{{ fullListError }} <button type="button" @click="fullListType ? loadFullListPage() : reloadAccount()">重试</button></p>
    <template v-else>
      <AwPendingList v-if="fullListType !== 'initiated'" :tm="tm" />
      <AwInitiatedList v-if="fullListType !== 'pending'" :tm="tm" />
    </template>
    <AwDetailModal :tm="tm" />
  </div>
</template>

<script setup lang="ts">
// 原超大 SFC 已拆分至 ./approval-workspace/（子组件 + composables + 独立 CSS）；
// 入口保持对外路径/默认导出不变，仅做组装。
import AwEtlAutoIngestList from './approval-workspace/AwEtlAutoIngestList.vue'
import AwStatsCards from './approval-workspace/AwStatsCards.vue'
import AwPendingList from './approval-workspace/AwPendingList.vue'
import AwInitiatedList from './approval-workspace/AwInitiatedList.vue'
import AwDetailModal from './approval-workspace/AwDetailModal.vue'
import { assembleApprovalWorkspace } from './approval-workspace/assemble'

const tm = assembleApprovalWorkspace()
const { fullListType, fullListPage, fullListPageCount, fullListLoading, fullListError, closeFullList, loadFullListPage, reloadAccount } = tm
</script>

<style scoped src="./approval-workspace/approval-workspace.css"></style>
