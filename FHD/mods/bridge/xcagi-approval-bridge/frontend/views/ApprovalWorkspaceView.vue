<template>
  <div class="approval-workspace-view">
    <TabsRoot class="approval-queue" :model-value="activeQueue" @update:model-value="selectQueue">
      <div class="approval-queue-toolbar">
        <TabsList class="approval-queue-tabs" aria-label="审批筛选">
          <TabsTrigger
            v-for="queue in queues"
            :key="queue.key"
            :value="queue.key"
            :data-tutorial-id="'approval-queue-' + queue.key"
            class="approval-queue-tab"
          >
            {{ queue.label }}
            <span v-if="!loading" class="approval-queue-count">{{ stats[queue.key] }}</span>
          </TabsTrigger>
        </TabsList>
        <div class="approval-queue-actions">
          <button
            v-if="activeQueue !== 'pending' && completedInitiatedCount"
            type="button" class="btn-link btn-cleanup" :disabled="cleanupLoading" @click="cleanupCompleted"
          >
            <i class="fa fa-trash-o" aria-hidden="true"></i> 清理已完成
          </button>
          <button v-if="fullListType" type="button" class="btn-link" @click="closeFullList">返回工作台</button>
          <button v-else type="button" class="btn-link" :disabled="loading || !!fullListError" @click="viewAll">查看全部</button>
          <button type="button" class="btn-link queue-refresh" :disabled="loading || fullListLoading" @click="reloadAccount">
            <i class="fa fa-refresh" :class="{ 'fa-spin': loading || fullListLoading }" aria-hidden="true"></i> 刷新
          </button>
        </div>
      </div>
      <TabsContent v-for="queue in queues" :key="queue.key" :value="queue.key" class="approval-queue-panel">
        <p v-if="loading || fullListLoading" class="queue-status" role="status">正在读取审批列表…</p>
        <p v-else-if="fullListError" class="queue-status" role="alert">
          {{ fullListError }}
          <button type="button" class="btn-link" @click="fullListType ? loadFullListPage() : reloadAccount()">重试</button>
        </p>
        <AwPendingList v-else-if="queue.key === 'pending'" :tm="tm" />
        <AwInitiatedList v-else :tm="tm" :empty-label="queue.emptyLabel" />
        <nav v-if="fullListType" class="approval-list-pages" aria-label="完整审批列表">
          <button type="button" class="btn-link" :disabled="fullListLoading || fullListPage <= 1" @click="loadFullListPage(fullListPage - 1)">上一页</button>
          <span>第 {{ fullListPage }} / {{ fullListPageCount }} 页</span>
          <button type="button" class="btn-link" :disabled="fullListLoading || fullListPage >= fullListPageCount" @click="loadFullListPage(fullListPage + 1)">下一页</button>
        </nav>
      </TabsContent>
    </TabsRoot>
    <AwDetailModal :tm="tm" />
  </div>
</template>

<script setup lang="ts">
import { TabsContent, TabsList, TabsRoot, TabsTrigger } from '@/components/ui/tabs'
import AwPendingList from './approval-workspace/AwPendingList.vue'
import AwInitiatedList from './approval-workspace/AwInitiatedList.vue'
import AwDetailModal from './approval-workspace/AwDetailModal.vue'
import { assembleApprovalWorkspace } from './approval-workspace/assemble'

const tm = assembleApprovalWorkspace()
const {
  stats, activeQueue, selectQueue, viewAll, closeFullList, loadFullListPage, reloadAccount,
  fullListType, fullListPage, fullListPageCount, fullListLoading, fullListError, loading,
  completedInitiatedCount, cleanupLoading, cleanupCompleted,
} = tm

const queues = [
  { key: 'pending', label: '待我审批' },
  { key: 'initiated', label: '我发起的', emptyLabel: '暂无发起的审批' },
  { key: 'approved', label: '已通过', emptyLabel: '暂无已通过的审批' },
  { key: 'rejected', label: '已拒绝', emptyLabel: '暂无已拒绝的审批' },
] as const
</script>

<style scoped src="./approval-workspace/approval-workspace.css"></style>
