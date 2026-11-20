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

  type Source = 'manual' | 'customer_feedback';

  interface CustomerFeedback {
    ticket_id: number;
    ticket_no: string;
    selected_at: string;
    candidates_considered: number;
    allocated_worker_slots: number;
    validation_budget_seconds: number;
  }

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
      plan?: { public_body: string; private_customer_feedback?: { reproduction: string[] } };
      optimization?: { status: string; candidate?: { plan?: string } };
      verification?: {
        url?: string;
        target_sha?: string;
        evidence_digest?: string;
        reason?: string;
      };
      execution?: { reason?: string };
      delivery?: {
        status?: string;
        reason?: string;
        merge_sha?: string;
        release_sha?: string;
        url?: string;
        identity?: { product_version?: string };
      };
      knowledge?: { recorded?: boolean };
      impact?: {
        status: string;
        reason?: string;
        release_sha?: string;
        verified_at?: string;
        experiment?: { status: string; metric_name?: string; sample_size?: number; lift?: number };
        commercial?: { status: string; matching_paid_orders?: number; matched_paid_amount_cents?: number };
      };
    };
    effects: {
      issue_number?: number;
      run_id?: number;
      pull_request_number?: number;
      customer_feedback?: CustomerFeedback;
    };
  }
  interface Overview {
    items: Run[];
    total: number;
    standard_version: string;
    domains: { id: string; name: string; criteria: { id: string; requirement: string }[] }[];
    templates: { id: string; name: string; criterion_ids: string[]; customer_feedback?: boolean }[];
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
    draft = ref({ request_id: '', template_id: '', title: '', goal: '', source: 'manual' as Source });
  const labels: Record<string, string> = {
    created: '待编排',
    planned: '已规划',
    awaiting_dispatch_approval: '待派工审批',
    authorized: '已批准',
    waiting_execution: '云端执行中',
    waiting_credential_isolation: '等待凭据隔离',
    verifying: '独立验证中',
    awaiting_acceptance: '待验收',
    accepted: '已验收',
    branch_accepted: '分支已验收，交付待核对',
    waiting_delivery: '等待上线验收',
    delivered: '上线已核验',
    waiting_customer_impact: '待原客户复测',
    customer_impact_verified: '原客户已确认',
    customer_impact_rejected: '原客户复测后重开',
    completed: '已上线并归档',
    rejected: '已拒绝',
    failed: '未通过',
    cancelled: '已取消',
  };
  const basePhases = [
    '18 域任务',
    'Retort 规划',
    'RSI 辅助',
    '派工审批',
    '云端执行',
    '独立验证',
    '管理端验收',
    '上线验收',
    '知识回流',
  ];
  const reasons: Record<string, string> = {
    customer_feedback_requires_non_exportable_model_credentials: '客户反馈修复已暂停，等待不可导出的执行凭据；现有结果仍可核对',
    frozen_source_changed: '执行版本与已批准方案不一致，请按当前版本重新建单',
    awaiting_pull_request: '等待关联任务的代码 PR',
    waiting_cloud_device: '等待云端员工上线',
    issue_response_unconfirmed: 'GitHub 任务回执待核对',
    runner_response_unconfirmed: '云端执行回执待核对',
    github_run_failed: '云端执行或独立验证未通过',
    employee_receipt_incomplete: '员工执行证据不完整',
    awaiting_protected_merge: '等待代码审核与主干合入',
    awaiting_authorized_production_release: '等待正式发布审批与部署',
    production_release_not_successful: '发布尚未成功，继续核对原发布任务',
    production_receipt_unavailable: '发布证据待核对',
    active_release_does_not_contain_merge: '等待包含本次修复的正式发布',
    active_release_not_present_on_main: '当前发布提交待在主干核实',
    production_release_manifest_unconfirmed: '正式发布清单待核对',
    production_release_acceptance_incomplete: '发布签名和运行验收证据待补齐',
    production_release_evidence_mismatch: '制品或签名与正式发布记录未对齐',
    delivery_evidence_unavailable: '暂时无法读取交付证据',
    delivery_repository_unconfirmed: '发布证据的仓库待核对',
    health_release_id_mismatch: '线上运行版本与正式发布清单未对齐',
    health_sha_mismatch: '线上运行版本尚未与本次交付对齐',
    health_artifact_digest_mismatch: '线上程序与发布制品尚未匹配',
    accepted_pull_request_identity_changed: '验收后的代码已变化，需要重新验证',
    pull_request_closed_without_merge: '代码提案已关闭，尚未合入',
    awaiting_ticket_release_binding: '原单尚未绑定这次发布，请核对原处理进度',
    awaiting_original_customer_receipt: '已通知原提交人，等待原场景复测',
    original_ticket_unavailable: '原单不可读取，效果待核对',
    awaiting_experiment_result: '等待已绑定实验的有效结果',
    awaiting_paid_outcome: '等待同版付费与客户验收凭证',
  };
  const stages: Record<string, number> = {
    created: 0,
    planned: 2,
    awaiting_dispatch_approval: 3,
    authorized: 4,
    waiting_execution: 4,
    waiting_credential_isolation: 4,
    verifying: 5,
    awaiting_acceptance: 6,
    accepted: 7,
    branch_accepted: 7,
    waiting_delivery: 7,
    delivered: 8,
    waiting_customer_impact: 8,
    customer_impact_verified: 9,
    customer_impact_rejected: 8,
    completed: 9,
  };
  const feedback = computed(() => detail.value?.effects.customer_feedback);
  const impact = computed(() => detail.value?.snapshot.impact);
  const phases = computed(() =>
    feedback.value ? [...basePhases.slice(0, -1), '客户复测', '知识回流'] : basePhases
  );
  const active = computed(() =>
    detail.value?.status === 'completed' ? phases.value.length : stages[detail.value?.status || ''] ?? 0
  );
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
  const feedbackTemplates = computed(() => data.value?.templates.filter(t => t.customer_feedback) || []);
  const availableTemplates = computed(() =>
    draft.value.source === 'customer_feedback' ? feedbackTemplates.value : data.value?.templates
  );
  const canCreate = computed(
    () => !!draft.value.template_id &&
      (draft.value.source === 'customer_feedback' || (!!draft.value.title.trim() && !!draft.value.goal.trim()))
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
  function newRun(source: Source = 'manual') {
    draft.value = { request_id: crypto.randomUUID(), template_id: '', title: '', goal: '', source };
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
        <el-button :disabled="!data?.templates.length || busy" @click="newRun()"
          >新建改进任务</el-button
        >
        <el-button type="primary" :disabled="!feedbackTemplates.length || busy" @click="newRun('customer_feedback')"
          >AI 从客户反馈选题</el-button
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
      <el-table-column label="来源" min-width="112">
        <template #default="{ row }">
          <el-tag v-if="row.effects.customer_feedback" type="info">客户反馈</el-tag>
          <span v-else>验收方案</span>
        </template>
      </el-table-column>
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
      :title="creating ? (draft.source === 'customer_feedback' ? 'AI 从客户反馈选题' : '新建改进任务') : detail?.protocol.title || '改进任务'"
      size="min(780px, 96vw)"
      append-to-body
      destroy-on-close
    >
      <el-alert v-if="error" :title="error" type="error" :closable="false" />
      <el-form v-if="creating" label-position="top" @submit.prevent="create">
        <el-form-item v-if="draft.source === 'manual'" label="任务名称"
          ><el-input v-model="draft.title" maxlength="160" aria-label="任务名称"
        /></el-form-item>
        <el-form-item v-if="draft.source === 'manual'" label="目标和验收场景"
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
              v-for="template in availableTemplates"
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
          :process-status="['failed', 'customer_impact_rejected'].includes(detail.status) ? 'error' : 'process'"
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
          <el-descriptions-item v-if="detail.snapshot.delivery?.reason" label="交付状态">{{
            reasons[detail.snapshot.delivery.reason] || '交付证据待核对'
          }}</el-descriptions-item>
          <el-descriptions-item v-if="feedback" label="选题依据">
            <a :href="`/admin/customer-service-tickets/${feedback.ticket_id}`">原工单 {{ feedback.ticket_no }}</a>
            AI 在 {{ feedback.candidates_considered }} 条反馈中选择
          </el-descriptions-item>
          <el-descriptions-item label="目标">{{ detail.protocol.goal }}</el-descriptions-item>
          <el-descriptions-item v-if="feedback" label="资源">
            {{ feedback.allocated_worker_slots }} 个云端执行名额 · 独立验证上限 {{ feedback.validation_budget_seconds }} 秒
            · {{ detail.effects.run_id ? '执行已登记' : '待审批派工' }}
          </el-descriptions-item>
          <el-descriptions-item v-if="feedback" label="生产版本">{{
            detail.snapshot.delivery?.merge_sha || '待正式上线'
          }}</el-descriptions-item>
          <el-descriptions-item v-if="feedback" label="客户效果">
            <el-tag v-if="impact?.verified_at && impact.status !== 'customer_impact_rejected'" type="success">
              原客户已确认解决
            </el-tag>
            <el-tag v-else-if="detail.snapshot.impact?.status === 'customer_impact_rejected'" type="danger">
              原客户反馈仍有问题
            </el-tag>
            <span v-else>{{ reasons[detail.snapshot.impact?.reason || ''] || '待生产验证' }}</span>
            <span v-if="impact?.verified_at">
              · {{ new Date(impact.verified_at).toLocaleString('zh-CN') }}
            </span>
            <span v-if="impact?.reason && impact.verified_at"> · {{ reasons[impact.reason] }}</span>
          </el-descriptions-item>
          <el-descriptions-item v-if="feedback" label="群体效果">
            <span v-if="impact?.experiment?.status === 'measured'">
              {{ impact.experiment.metric_name }} · {{ impact.experiment.sample_size }} 个样本
              · 相对变化 {{ ((impact.experiment.lift || 0) * 100).toFixed(2) }}%
            </span>
            <span v-else>{{ impact?.experiment?.status === 'not_configured' ? '未配置实验' : '待有效实验结果' }}</span>
          </el-descriptions-item>
          <el-descriptions-item v-if="feedback" label="商业结果">
            <span v-if="impact?.commercial?.status === 'verified'">
              {{ impact.commercial.matching_paid_orders }} 笔同版订单通过核验 · 实付
              {{ ((impact.commercial.matched_paid_amount_cents || 0) / 100).toFixed(2) }} 元
            </span>
            <span v-else>{{ impact?.commercial?.status === 'not_configured' ? '未配置商业验证' : '待同版付费凭证' }}</span>
          </el-descriptions-item>
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
          <template v-if="detail.snapshot.delivery?.status === 'deployment_verified'">
            <el-descriptions-item label="合入提交">{{ detail.snapshot.delivery.merge_sha }}</el-descriptions-item>
            <el-descriptions-item label="正式发布">{{ detail.snapshot.delivery.identity?.product_version }}
              {{ detail.snapshot.delivery.release_sha || detail.snapshot.delivery.merge_sha }}
            </el-descriptions-item>
          </template>
          <el-descriptions-item label="执行证据">
            <a
              v-if="detail.snapshot.delivery?.url"
              :href="detail.snapshot.delivery.url"
              target="_blank"
              rel="noopener noreferrer"
              >{{ detail.snapshot.delivery.status === 'deployment_verified' ? '正式发布验收记录' : '发布工作流' }}</a
            >
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
          <template v-if="detail.snapshot.plan?.private_customer_feedback">
            <h4>本次批准的客户复现场景（仅交给授权执行任务）</h4>
            <pre class="retort-preview">{{
              detail.snapshot.plan.private_customer_feedback.reproduction.join('\n\n')
            }}</pre>
          </template>
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
          >{{ draft.source === 'customer_feedback' ? '从原单选题并生成待审方案' : '生成待审方案' }}</el-button
        >
        <template v-else-if="pending">
          <el-button :disabled="busy" @click="decide(false)">拒绝</el-button>
          <el-button type="primary" :loading="busy" @click="decide(true)">{{
            pending.kind === 'acceptance' ? '确认验收' : '批准并派工'
          }}</el-button>
        </template>
        <el-button
          v-else-if="
            detail && !['completed', 'failed', 'rejected', 'cancelled', 'customer_impact_rejected'].includes(detail.status)
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
