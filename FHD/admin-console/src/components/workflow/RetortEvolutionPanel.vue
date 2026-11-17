<script setup lang="ts">
  import { computed, onMounted, ref } from 'vue';
  import { useIntervalFn } from '@vueuse/core';
  import {
    ElAlert,
    ElButton,
    ElDescriptions,
    ElDescriptionsItem,
    ElDrawer,
    ElEmpty,
    ElForm,
    ElFormItem,
    ElInput,
    ElOption,
    ElPagination,
    ElSelect,
    ElStep,
    ElSteps,
    ElTable,
    ElTableColumn,
    ElTag,
  } from 'element-plus';
  import api, { ApiError } from '@/api/core';

  interface Run {
    id: string;
    status: string;
    error: string;
    updated_at: string;
    protocol: {
      title: string;
      goal: string;
      repository: string;
      source_sha: string;
      criterion_ids: string[];
      criteria: { id: string; domain_name: string; requirement: string }[];
    };
    snapshot: {
      pending?: { kind: string; digest?: string }[];
      plan?: { public_body: string };
      optimization?: { status: string; candidate?: { plan?: string } };
      verification?: {
        url?: string;
        target_sha?: string;
        evidence_digest?: string;
        reason?: string;
      };
      execution?: { reason?: string };
      knowledge?: { recorded?: boolean };
    };
    effects: { issue_number?: number; run_id?: number; pull_request_number?: number };
  }
  interface Overview {
    items: Run[];
    total: number;
    standard_version: string;
    domains: { id: string; name: string; criteria: { id: string; requirement: string }[] }[];
    templates: { id: string; name: string; criterion_ids: string[] }[];
    connections: Record<string, boolean>;
  }
  const base = '/api/xcmax/admin/retort-evolution';
  const data = ref<Overview>(),
    detail = ref<Run>(),
    page = ref(1),
    busy = ref(false),
    error = ref('');
  const drawer = ref(false),
    creating = ref(false),
    draft = ref({ request_id: '', template_id: '', title: '', goal: '' });
  const labels: Record<string, string> = {
    created: '待编排',
    planned: '已规划',
    awaiting_dispatch_approval: '待派工审批',
    authorized: '已批准',
    waiting_execution: '云端执行中',
    verifying: '独立验证中',
    awaiting_acceptance: '待验收',
    accepted: '已验收',
    completed: '已验收并归档',
    rejected: '已拒绝',
    failed: '未通过',
    cancelled: '已取消',
  };
  const phases = [
    '18 域任务',
    'Retort 规划',
    'RSI 辅助',
    '派工审批',
    '云端执行',
    '独立验证',
    '管理端验收',
    '知识回流',
  ];
  const reasons: Record<string, string> = {
    frozen_source_changed: '执行版本与已批准方案不一致，请按当前版本重新建单',
    awaiting_pull_request: '等待关联任务的代码 PR',
    waiting_cloud_device: '等待云端员工上线',
    issue_response_unconfirmed: 'GitHub 任务回执待核对',
    runner_response_unconfirmed: '云端执行回执待核对',
    github_run_failed: '云端执行或独立验证未通过',
    employee_receipt_incomplete: '员工执行证据不完整',
  };
  const stages: Record<string, number> = {
    created: 0,
    planned: 2,
    awaiting_dispatch_approval: 3,
    authorized: 4,
    waiting_execution: 4,
    verifying: 5,
    awaiting_acceptance: 6,
    accepted: 7,
    completed: 8,
  };
  const active = computed(() => stages[detail.value?.status || ''] ?? 0);
  const pending = computed(() =>
    detail.value?.snapshot.pending?.find((p) =>
      ['dispatch_approval', 'acceptance'].includes(p.kind)
    )
  );
  const missing = computed(() =>
    Object.entries({
      checkpoint: '持久存储',
      github: 'GitHub',
      employees: '云端员工',
      protocols: '验收方案',
      evidence: '持久证据存储',
    })
      .filter(([key]) => data.value && !data.value.connections[key])
      .map(([, value]) => value)
  );
  const criteria = computed(() => {
    const ids =
      data.value?.templates.find((t) => t.id === draft.value.template_id)?.criterion_ids || [];
    return (
      data.value?.domains.flatMap((d) =>
        d.criteria.filter((c) => ids.includes(c.id)).map((c) => ({ ...c, domain: d.name }))
      ) || []
    );
  });
  const canCreate = computed(
    () => !!draft.value.title.trim() && !!draft.value.goal.trim() && !!draft.value.template_id
  );
  async function action(fn: () => Promise<void>) {
    busy.value = true;
    error.value = '';
    try {
      await fn();
    } catch (e) {
      error.value =
        e instanceof ApiError && e.status === 404
          ? '当前管理服务尚未接通改进闭环'
          : e instanceof Error
            ? e.message
            : '操作未确认，请刷新核对';
    } finally {
      busy.value = false;
    }
  }
  async function load() {
    data.value = (await api.get(base, { offset: (page.value - 1) * 8, limit: 8 })) as Overview;
  }
  function refresh() {
    return action(async () => {
      await load();
      if (drawer.value && detail.value) await read(detail.value.id);
    });
  }
  async function read(id: string) {
    detail.value = (await api.get(`${base}/${encodeURIComponent(id)}`)) as Run;
  }
  function inspect(id: string) {
    return action(async () => {
      await read(id);
      creating.value = false;
      drawer.value = true;
    });
  }
  function newRun() {
    draft.value = { request_id: crypto.randomUUID(), template_id: '', title: '', goal: '' };
    detail.value = undefined;
    creating.value = true;
    drawer.value = true;
  }
  function create() {
    return action(async () => {
      const result = (await api.post(base, draft.value)) as { id: string };
      await read(result.id);
      creating.value = false;
      await load();
    });
  }
  function decide(approved: boolean) {
    return action(async () => {
      if (!detail.value || !pending.value?.digest) return;
      await api.post(`${base}/${detail.value.id}/decision`, {
        digest: pending.value.digest,
        approved,
      });
      await read(detail.value.id);
      await load();
    });
  }
  function resume() {
    return action(async () => {
      if (!detail.value) return;
      await api.post(`${base}/${detail.value.id}/resume`, {});
      await read(detail.value.id);
      await load();
    });
  }
  function issueUrl(run: Run) {
    return `https://github.com/${run.protocol.repository}/issues/${run.effects.issue_number}`;
  }
  function runUrl(run: Run) {
    return `https://github.com/${run.protocol.repository}/actions/runs/${run.effects.run_id}`;
  }
  onMounted(refresh);
  useIntervalFn(() => {
    if (document.visibilityState === 'visible' && !busy.value) void refresh();
  }, 15000);
</script>

<template>
  <section class="retort-panel" aria-label="Retort 改进闭环">
    <div class="retort-toolbar">
      <span>{{ data ? `${data.domains.length} 域 · ${data.total} 个改进任务` : '改进任务' }}</span>
      <div>
        <el-button :loading="busy" @click="refresh">刷新</el-button>
        <el-button type="primary" :disabled="!data?.templates.length || busy" @click="newRun"
          >新建改进任务</el-button
        >
      </div>
    </div>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <el-alert
      v-if="missing.length"
      :title="`待接通：${missing.join('、')}`"
      type="warning"
      :closable="false"
    />
    <el-table :data="data?.items || []" height="100%" class="retort-table" row-key="id">
      <el-table-column
        prop="protocol.title"
        label="改进任务"
        min-width="180"
        show-overflow-tooltip
      />
      <el-table-column label="验收范围" min-width="100"
        ><template #default="{ row }"
          >{{ row.protocol.criterion_ids.length }} 项要求</template
        ></el-table-column
      >
      <el-table-column label="进度" min-width="145"
        ><template #default="{ row }">
          <el-tag
            :type="
              row.status === 'completed' ? 'success' : row.status === 'failed' ? 'danger' : 'info'
            "
            >{{ labels[row.status] || '待核对' }}</el-tag
          >
        </template></el-table-column
      >
      <el-table-column label="操作" width="90" fixed="right"
        ><template #default="{ row }">
          <el-button link type="primary" @click="inspect(row.id)">查看</el-button>
        </template></el-table-column
      >
      <template #empty
        ><el-empty :description="data ? '暂无改进任务' : '尚未取得任务记录'" :image-size="55"
      /></template>
    </el-table>
    <el-pagination
      v-model:current-page="page"
      :total="data?.total || 0"
      :page-size="8"
      layout="prev, pager, next"
      @current-change="refresh"
    />
    <el-drawer
      v-model="drawer"
      :title="creating ? '新建改进任务' : detail?.protocol.title || '改进任务'"
      size="min(780px, 96vw)"
      append-to-body
      destroy-on-close
    >
      <el-alert v-if="error" :title="error" type="error" :closable="false" />
      <el-form v-if="creating" label-position="top" @submit.prevent="create">
        <el-form-item label="任务名称"
          ><el-input v-model="draft.title" maxlength="160" aria-label="任务名称"
        /></el-form-item>
        <el-form-item label="目标和验收场景"
          ><el-input
            v-model="draft.goal"
            type="textarea"
            :rows="4"
            maxlength="12000"
            aria-label="目标和验收场景"
        /></el-form-item>
        <el-form-item label="验收方案"
          ><el-select v-model="draft.template_id" aria-label="验收方案" style="width: 100%">
            <el-option
              v-for="template in data?.templates"
              :key="template.id"
              :label="template.name"
              :value="template.id"
            /> </el-select
        ></el-form-item>
        <el-table :data="criteria" max-height="240"
          ><el-table-column prop="domain" label="能力域" width="160" /><el-table-column
            prop="requirement"
            label="验收要求"
        /></el-table>
      </el-form>
      <template v-else-if="detail">
        <el-steps
          :active="active"
          :process-status="detail.status === 'failed' ? 'error' : 'process'"
          finish-status="success"
          align-center
        >
          <el-step v-for="phase in phases" :key="phase" :title="phase" />
        </el-steps>
        <el-alert
          v-if="detail.error || detail.snapshot.verification?.reason"
          :title="detail.error || detail.snapshot.verification?.reason || ''"
          type="error"
          :closable="false"
        />
        <el-descriptions :column="1" border class="retort-details">
          <el-descriptions-item label="状态">{{
            labels[detail.status] || '待核对'
          }}</el-descriptions-item>
          <el-descriptions-item v-if="detail.snapshot.execution?.reason" label="待处理">{{
            reasons[detail.snapshot.execution.reason] || '执行结果待核对'
          }}</el-descriptions-item>
          <el-descriptions-item label="目标">{{ detail.protocol.goal }}</el-descriptions-item>
          <el-descriptions-item label="RSI 辅助">{{
            detail.snapshot.optimization?.status === 'proposed'
              ? '实测方案待批准'
              : detail.snapshot.optimization?.status === 'no_verified_improvement'
                ? '未发现实测改善'
                : detail.snapshot.optimization?.status === 'experiment_failed'
                  ? '辅助实验未通过，保留原方案'
                  : '等待实测基线'
          }}</el-descriptions-item>
          <el-descriptions-item label="18 域评级">未评级</el-descriptions-item>
          <el-descriptions-item label="代码版本">{{
            detail.snapshot.verification?.target_sha || detail.protocol.source_sha
          }}</el-descriptions-item>
          <el-descriptions-item label="执行证据">
            <a
              v-if="detail.effects.pull_request_number"
              :href="`https://github.com/${detail.protocol.repository}/pull/${detail.effects.pull_request_number}`"
              target="_blank"
              rel="noopener noreferrer"
              >代码 PR</a
            >
            <a
              v-if="detail.effects.issue_number"
              :href="issueUrl(detail)"
              target="_blank"
              rel="noopener noreferrer"
              >GitHub 任务</a
            >
            <a
              v-if="detail.effects.run_id"
              :href="runUrl(detail)"
              target="_blank"
              rel="noopener noreferrer"
              >执行与验证记录</a
            >
            <span v-if="!detail.effects.run_id">尚未取得</span>
          </el-descriptions-item>
          <el-descriptions-item label="知识回流">{{
            detail.snapshot.knowledge?.recorded ? '已归档验收结果' : '等待验收'
          }}</el-descriptions-item>
        </el-descriptions>
        <el-table :data="detail.protocol.criteria" max-height="240"
          ><el-table-column prop="domain_name" label="能力域" width="160" /><el-table-column
            prop="requirement"
            label="验收要求"
        /></el-table>
        <template v-if="pending?.kind === 'dispatch_approval'">
          <h4>将发布到 GitHub 的任务</h4>
          <pre class="retort-preview">{{ detail.snapshot.plan?.public_body }}</pre>
          <template v-if="detail.snapshot.optimization?.status === 'proposed'">
            <h4>经独立试验选出的辅助方案</h4>
            <pre class="retort-preview">{{ detail.snapshot.optimization.candidate?.plan }}</pre>
          </template>
        </template>
        <el-alert
          v-if="pending?.kind === 'acceptance'"
          title="独立检查已通过，等待确认实际任务效果"
          type="info"
          :closable="false"
        />
      </template>
      <template #footer>
        <el-button @click="drawer = false">关闭</el-button>
        <el-button
          v-if="creating"
          type="primary"
          :disabled="!canCreate"
          :loading="busy"
          @click="create"
          >生成待审方案</el-button
        >
        <template v-else-if="pending">
          <el-button :disabled="busy" @click="decide(false)">拒绝</el-button>
          <el-button type="primary" :loading="busy" @click="decide(true)">{{
            pending.kind === 'acceptance' ? '确认验收' : '批准并派工'
          }}</el-button>
        </template>
        <el-button
          v-else-if="
            detail && !['completed', 'failed', 'rejected', 'cancelled'].includes(detail.status)
          "
          :loading="busy"
          @click="resume"
          >核对并继续</el-button
        >
      </template>
    </el-drawer>
  </section>
</template>

<style scoped>
  .retort-panel {
    display: flex;
    flex-direction: column;
    gap: 12px;
    height: 100%;
    min-height: 0;
  }
  .retort-toolbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
  }
  .retort-table {
    flex: 1;
    min-height: 0;
  }
  .retort-details {
    margin: 22px 0;
    overflow-wrap: anywhere;
  }
  .retort-details a {
    margin-right: 16px;
    color: var(--admin-primary, #3159c9);
  }
  .retort-preview {
    white-space: pre-wrap;
    overflow-wrap: anywhere;
    max-height: 240px;
    overflow: auto;
    font: inherit;
    background: var(--admin-surface, #f8fafc);
    padding: 16px;
    border-radius: 8px;
  }
  :deep(.el-step__title) {
    font-size: 12px;
    line-height: 18px;
  }
</style>
