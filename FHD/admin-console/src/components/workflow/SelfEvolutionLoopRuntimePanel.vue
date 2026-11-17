<script setup lang="ts">
  import 'element-plus/dist/index.css';
  import { computed, ref, watch } from 'vue';
  import { useRouter } from 'vue-router';
  import {
    ElAlert,
    ElButton,
    ElDescriptions,
    ElDescriptionsItem,
    ElDrawer,
    ElEmpty,
    ElInput,
    ElPagination,
    ElSwitch,
    ElTabPane,
    ElTable,
    ElTableColumn,
    ElTabs,
    ElTag,
    ElTimeline,
    ElTimelineItem,
  } from 'element-plus';
  import {
    useLoopRuntimePanel,
    asArray,
    asRecord,
    firstText,
  } from '@host/composables/useLoopRuntimePanel';
  import MaintenanceExecutionPanel from '../admin/MaintenanceExecutionPanel.vue';
  import RetortEvolutionPanel from './RetortEvolutionPanel.vue';

  withDefaults(defineProps<{ compact?: boolean; surface?: string }>(), { compact: false });
  const emit = defineEmits<{ snapshot: [value: Record<string, unknown> | null] }>();
  const router = useRouter();
  const { raw, loading, error, refresh, connection } = useLoopRuntimePanel(() => 80);
  const showHeartbeat = ref(false);
  const pane = ref('runs'),
    search = ref(''),
    page = ref(1),
    selected = ref(''),
    drawer = ref(false);
  const fresh = computed(() => connection.value === 'connected');
  const connectionLabel = computed(
    () =>
      ({
        loading: '正在连接',
        empty: '尚未连接',
        error: '连接异常',
        stale: '数据已过期',
        connected: '监控已连接',
      })[connection.value]
  );
  const policy = computed(() => asRecord(raw.value?.policy));
  const gate = computed(() => asRecord(raw.value?.current_gate));
  const openIds = computed(() => asArray(asRecord(raw.value?.evidence).open_run_ids));
  const openItems = computed(() => asArray(asRecord(raw.value?.memory).open_items).map(asRecord));
  const pendingKnown = computed(
    () => fresh.value && Array.isArray(asRecord(raw.value?.memory).open_items)
  );
  const records = computed(() =>
    asArray(raw.value?.run_timelines)
      .map(asRecord)
      .map((row) => {
        const evidence = asArray(asRecord(raw.value?.evidence).recent_rows).map(asRecord);
        const items: Record<string, unknown>[] = asArray(row.items)
          .map(asRecord)
          .map((item) => ({
            ...item,
            error: firstText(
              item.error,
              evidence.find(
                (record) =>
                  record.run_id === row.run_id &&
                  record.phase === item.phase &&
                  record.step === item.step &&
                  Date.parse(firstText(record.timestamp, record.created_at)) ===
                    Date.parse(firstText(item.created_at))
              )?.error
            ),
          }));
        const last = items[items.length - 1] || {};
        const completed = [...items].reverse().find((item) => item.phase === 'complete');
        const failure = (completed ? [completed] : items).some(
          (item) =>
            ['failed', 'failure', 'error', 'timeout', 'timed_out'].includes(
              firstText(item.status)
            ) || item.qa_verdict === 'FAIL'
        );
        const state =
          row.open === true
            ? '执行中'
            : items.length > 0 && items.every((item) => item.phase === 'heartbeat')
              ? '心跳记录'
              : failure
                ? '执行异常'
                : completed
                  ? '已结束，待验收'
                  : '待核对';
        return {
          id: firstText(row.run_id),
          items,
          state,
          time: firstText(last.created_at),
          step: stepLabel(firstText(last.label, last.step, last.phase, '等待回执')),
        };
      })
      .reverse()
  );
  const filtered = computed(() =>
    records.value.filter(
      (row) =>
        (showHeartbeat.value || row.state !== '心跳记录') &&
        `${row.id} ${row.state} ${row.step}`
          .toLowerCase()
          .includes(search.value.trim().toLowerCase())
    )
  );
  const rows = computed(() => filtered.value.slice((page.value - 1) * 8, page.value * 8));
  const detail = computed(() => records.value.find((row) => row.id === selected.value));
  const deployment = computed(() =>
    !fresh.value
      ? '待核实'
      : policy.value.auto_dispatch_deploy === true
        ? policy.value.auto_dispatch_deploy_dry_run === true
          ? '仅演练'
          : '已开启'
        : policy.value.auto_dispatch_deploy === false
          ? '已关闭'
          : '未提供'
  );
  const source = computed(() =>
    raw.value
      ? firstText(
          asRecord(raw.value.control_plane).host,
          asRecord(raw.value.control_plane).target === 'local' ? '本地维护服务' : '已配置的运营服务'
        )
      : '数据源待核实'
  );
  function time(value: unknown) {
    const date = new Date(String(value || ''));
    return Number.isNaN(date.valueOf()) ? '—' : date.toLocaleString('zh-CN', { hour12: false });
  }
  function inspect(id: string) {
    selected.value = id;
    drawer.value = true;
  }
  function pendingReason(row: Record<string, unknown>) {
    const lastError = records.value
      .find((run) => run.id === row.run_id)
      ?.items.slice()
      .reverse()
      .find((item) => item.error)?.error;
    return firstText(
      row.reason,
      row.message,
      row.detail,
      lastError,
      asArray(row.steps)
        .map((step) => stepLabel(String(step)))
        .join('、'),
      '未提供'
    );
  }
  function stepLabel(value: string) {
    return (
      (
        {
          heartbeat: '调度心跳',
          kb_salvage: '修复知识归档',
          code: '代码修复',
          review: '代码审查',
          qa: '测试验证',
        } as Record<string, string>
      )[value] || value
    );
  }
  function stepStatus(value: unknown) {
    return (
      (
        {
          succeeded: '执行成功',
          success: '执行成功',
          failed: '执行失败',
          failure: '执行失败',
          running: '执行中',
          completed: '已结束',
          skipped: '已跳过',
          cancelled: '已取消',
          timeout: '执行超时',
        } as Record<string, string>
      )[String(value)] || firstText(value, '等待回执')
    );
  }
  watch([search, showHeartbeat], () => {
    page.value = 1;
  });
  watch(filtered, (value) => {
    page.value = Math.min(page.value, Math.max(1, Math.ceil(value.length / 8)));
  });
  watch(raw, (value) => emit('snapshot', value));
</script>

<template>
  <section class="loop-console" aria-label="系统自动维护状态">
    <header class="loop-head">
      <div>
        <h3>系统自动维护状态</h3>
        <small>{{ source }} · 更新于 {{ time(raw?.generated_at) }}</small>
      </div>
      <div class="loop-actions">
        <el-tag :type="fresh ? 'success' : connection === 'error' ? 'danger' : 'info'">{{
          connectionLabel
        }}</el-tag>
        <el-button :loading="loading" @click="refresh">刷新</el-button>
        <el-button @click="router.push({ name: 'workflow-employee-space' })"
          >云端工作空间</el-button
        >
      </div>
    </header>
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon>
      <template v-if="raw" #default>保留上次记录，当前执行状态尚未核实。</template>
    </el-alert>
    <el-alert
      v-else-if="connection === 'stale'"
      title="监控快照已过期，当前执行状态尚未核实"
      type="warning"
      :closable="false"
      show-icon
    />
    <div class="loop-metrics">
      <div>
        <span>执行中</span><strong>{{ fresh ? openIds.length : '—' }}</strong>
      </div>
      <div>
        <span>待处理</span><strong>{{ pendingKnown ? openItems.length : '—' }}</strong>
      </div>
      <div>
        <span>触发状态</span
        ><strong>{{
          !fresh
            ? '待核实'
            : gate.should_run === true
              ? '等待调度'
              : gate.reason === 'cooldown'
                ? '冷却中'
                : gate.should_run === false
                  ? '未触发'
                  : '未提供'
        }}</strong>
      </div>
      <div>
        <span>自动部署策略</span><strong>{{ deployment }}</strong>
      </div>
    </div>
    <el-tabs v-model="pane" class="loop-tabs">
      <el-tab-pane label="运行记录" name="runs">
        <div class="loop-toolbar">
          <el-input
            v-model="search"
            clearable
            placeholder="搜索任务编号、状态或步骤"
            aria-label="搜索维护记录"
          /><el-switch
            v-model="showHeartbeat"
            active-text="心跳记录"
            aria-label="显示心跳记录"
          /><small>{{ raw ? `${filtered.length} 条近期记录` : '等待状态数据' }}</small>
        </div>
        <el-table :data="rows" height="100%" row-key="id" class="loop-table">
          <el-table-column prop="id" label="任务编号" min-width="170" show-overflow-tooltip />
          <el-table-column prop="state" label="执行状态" min-width="145" />
          <el-table-column prop="step" label="最近步骤" min-width="150" show-overflow-tooltip />
          <el-table-column label="更新时间" min-width="170"
            ><template #default="{ row }">{{ time(row.time) }}</template></el-table-column
          >
          <el-table-column label="操作" width="90" fixed="right"
            ><template #default="{ row }"
              ><el-button link type="primary" @click="inspect(row.id)"
                >查看详情</el-button
              ></template
            ></el-table-column
          >
          <template #empty
            ><el-empty
              :description="
                loading
                  ? '正在读取维护状态'
                  : !raw
                    ? '尚未取得运行记录'
                    : search
                      ? '没有匹配的记录'
                      : '暂无运行记录'
              "
              :image-size="60"
          /></template>
        </el-table>
        <el-pagination
          v-model:current-page="page"
          :page-size="8"
          :total="filtered.length"
          layout="prev, pager, next"
        />
      </el-tab-pane>
      <el-tab-pane label="待处理事项" name="pending">
        <div class="loop-toolbar">
          <span>{{ pendingKnown ? `${openItems.length} 项` : '待处理状态尚未核实' }}</span
          ><el-button @click="router.push({ name: 'autonomy-approval-hub' })">审批中心</el-button>
        </div>
        <el-table :data="openItems" height="100%">
          <el-table-column label="事项" min-width="160"
            ><template #default="{ row }">{{
              firstText(
                row.title,
                row.kind === 'failed_steps'
                  ? '执行步骤失败'
                  : row.kind === 'automated_remediation'
                    ? '等待自动修复'
                    : row.kind,
                '待核对事项'
              )
            }}</template></el-table-column
          >
          <el-table-column label="原因" min-width="200" show-overflow-tooltip
            ><template #default="{ row }">{{ pendingReason(row) }}</template></el-table-column
          >
          <el-table-column label="关联任务" min-width="150"
            ><template #default="{ row }">{{
              firstText(row.run_id, '—')
            }}</template></el-table-column
          >
          <el-table-column label="操作" width="90" fixed="right">
            <template #default="{ row }"
              ><el-button v-if="row.run_id" link type="primary" @click="inspect(String(row.run_id))"
                >查看详情</el-button
              ></template
            >
          </el-table-column>
          <template #empty
            ><el-empty
              :description="pendingKnown ? '暂无待处理事项' : '尚未取得有效状态'"
              :image-size="60"
          /></template>
        </el-table>
      </el-tab-pane>
      <el-tab-pane label="改进闭环" name="retort" lazy>
        <RetortEvolutionPanel v-if="pane === 'retort'" />
      </el-tab-pane>
      <el-tab-pane label="维护作业" name="maintenance" lazy
        ><div class="loop-maintenance">
          <MaintenanceExecutionPanel v-if="pane === 'maintenance'" /></div
      ></el-tab-pane>
    </el-tabs>
    <el-drawer
      v-model="drawer"
      title="维护任务详情"
      size="min(620px, 94vw)"
      append-to-body
      destroy-on-close
    >
      <template v-if="detail">
        <el-alert
          v-if="!fresh"
          title="以下为上次取得的记录，当前状态尚未核实"
          type="warning"
          :closable="false"
        />
        <el-descriptions :column="1" border
          ><el-descriptions-item label="任务编号">{{ detail.id }}</el-descriptions-item
          ><el-descriptions-item label="执行状态">{{ detail.state }}</el-descriptions-item
          ><el-descriptions-item label="验收">尚未核实</el-descriptions-item></el-descriptions
        >
        <el-timeline class="loop-timeline"
          ><el-timeline-item
            v-for="(item, index) in detail.items"
            :key="index"
            :timestamp="time(item.created_at)"
            placement="top"
          >
            <strong>{{ stepLabel(firstText(item.label, item.step, item.phase)) }}</strong>
            <p>{{ stepStatus(item.status) }}</p>
            <el-alert
              v-if="item.error"
              :title="String(item.error)"
              type="error"
              :closable="false"
            />
            <p v-if="item.employee_id">员工：{{ item.employee_id }}</p>
            <p v-if="item.para_task_id">Para 任务：{{ item.para_task_id }}</p>
            <p v-if="item.branch">分支：{{ item.branch }}</p>
            <p v-if="item.reason">{{ item.reason }}</p>
            <p v-if="item.qa_verdict">测试结论：{{ item.qa_verdict }}</p>
            <p v-for="(command, i) in asArray(item.qa_tested_commands)" :key="i">{{ command }}</p>
            <p v-if="item.review_verdict">审查结论：{{ item.review_verdict }}</p>
          </el-timeline-item></el-timeline
        >
      </template>
      <el-empty v-else description="该任务已不在近期记录中，请到工作空间查看归档" />
    </el-drawer>
  </section>
</template>

<style scoped>
  .loop-console {
    display: flex;
    flex-direction: column;
    gap: 14px;
    padding: 18px;
    height: 100%;
    min-height: 0;
    box-sizing: border-box;
    background: var(--admin-card-bg, #fff);
    color: var(--admin-text, #1e293b);
  }
  .loop-head,
  .loop-actions,
  .loop-toolbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
  }
  h3 {
    margin: 0 0 6px;
    font-size: 18px;
  }
  small,
  .loop-metrics span {
    color: var(--admin-muted, #64748b);
    font-size: 12px;
  }
  .loop-actions {
    flex-wrap: wrap;
    justify-content: flex-end;
  }
  .loop-actions :deep(.el-button + .el-button) {
    margin-left: 0;
  }
  .loop-metrics {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 12px;
  }
  .loop-metrics > div {
    border: 1px solid var(--admin-border, #e2e8f0);
    border-radius: 8px;
    padding: 12px 16px;
    display: grid;
    gap: 8px;
  }
  .loop-metrics strong {
    font-size: 20px;
    font-weight: 600;
  }
  .loop-tabs {
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
  }
  .loop-tabs :deep(.el-tabs__content) {
    flex: 1;
    min-height: 0;
  }
  .loop-tabs :deep(.el-tab-pane) {
    height: 100%;
    display: flex;
    flex-direction: column;
    gap: 12px;
  }
  .loop-toolbar :deep(.el-input) {
    max-width: 300px;
  }
  .loop-table {
    flex: 1;
    min-height: 0;
  }
  .loop-maintenance {
    overflow: auto;
    min-height: 0;
  }
  .loop-timeline {
    margin-top: 24px;
    padding-left: 10px;
  }
  .loop-timeline p {
    overflow-wrap: anywhere;
    margin: 6px 0;
    font-size: 13px;
  }
  @media (max-width: 700px) {
    .loop-head {
      align-items: flex-start;
      flex-direction: column;
    }
    .loop-metrics {
      gap: 6px;
    }
    .loop-metrics > div {
      padding: 10px;
    }
    .loop-metrics strong {
      font-size: 16px;
    }
  }
</style>
