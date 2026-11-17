<script setup lang="ts">
  import 'element-plus/dist/index.css';
  import { computed, ref, watch } from 'vue';
  import {
    ElAlert,
    ElButton,
    ElCheckbox,
    ElEmpty,
    ElInput,
    ElSteps,
    ElStep,
    ElTag,
  } from 'element-plus';
  import api from '@/api/core';

  type Receipt = {
    status: string;
    number?: number;
    url?: string;
    state?: string;
    execution_status?: string;
    conclusion?: string;
    error?: string;
  };
  type State = {
    repository: string;
    url: string;
    configured: boolean;
    para_configured?: boolean;
    issue?: Receipt;
    run?: Receipt;
    pulls: Receipt[];
    jobs?: { name: string; employee_id?: string; status: string; conclusion?: string }[];
    readback_error?: string;
  };
  const props = defineProps<{ ticketId: number; ticketStatus?: string }>();
  const emit = defineEmits<{ updated: [] }>();
  const state = ref<State | null>(null),
    error = ref(''),
    busy = ref(false),
    title = ref(''),
    body = ref(''),
    confirmed = ref(false);
  const preview = ref(false);
  const jobNames: Record<string, string> = {
    scout: '问题核查',
    fix: 'Para 修复',
    verify: '独立验证',
  };
  const jobStates: Record<string, string> = {
    success: '通过',
    failed: '失败',
    skipped: '未执行',
    cancelled: '已取消',
    completed: '已结束',
    in_progress: '执行中',
    pending: '等待回执',
    queued: '排队中',
  };
  let generation = 0,
    requestId = '';
  const editable = computed(
    () => !props.ticketStatus || ['open', 'processing'].includes(props.ticketStatus)
  );
  const step = computed(() =>
    state.value?.pulls.some((p) => p.state === 'merged')
      ? 3
      : state.value?.pulls.length
        ? 2
        : state.value?.issue?.number
          ? 1
          : 0
  );
  const runLabel = computed(() => {
    const run = state.value?.run;
    if (!run) return '尚未派工';
    return (
      (
        {
          success: '执行完成，待审查',
          failure: '执行失败',
          cancelled: '已取消',
          timed_out: '执行超时',
          queued: '排队中',
          in_progress: 'GitHub 临时机器执行中',
          running: 'GitHub 临时机器已就绪',
          runner_stopped: '执行器已停止，待核对',
          waiting: '等待批准',
          requested: '等待 GitHub 分配临时机器',
          submitted: '已提交，等待运行回执',
          pending: '等待 Para 执行回执',
          unknown: '派工结果待核对',
          dispatching: '正在派工',
        } as Record<string, string>
      )[run.conclusion || run.execution_status || run.status] || '等待核对执行状态'
    );
  });
  const endpoint = () => `/api/xcmax/admin/customer-service/tickets/${props.ticketId}/github`;
  function message(e: unknown): string {
    return e instanceof Error ? e.message : '请求失败，请刷新回执';
  }
  async function load() {
    const current = ++generation;
    try {
      const data = (await api.get(endpoint())) as State;
      if (current === generation) {
        state.value = data;
        error.value = '';
      }
    } catch (e) {
      if (current === generation) error.value = message(e);
    }
  }
  async function command(suffix: string, payload: object) {
    if (busy.value) return;
    busy.value = true;
    const id = props.ticketId;
    try {
      await api.post(endpoint() + suffix, payload);
      if (id === props.ticketId) {
        await load();
        emit('updated');
      }
    } catch (e) {
      if (id === props.ticketId) error.value = message(e);
    } finally {
      busy.value = false;
    }
  }
  function start() {
    if (!requestId) requestId = crypto.randomUUID();
    return command('/start', { request_id: requestId });
  }
  watch(
    () => props.ticketId,
    () => {
      state.value = null;
      error.value = '';
      title.value = '';
      body.value = '';
      confirmed.value = false;
      preview.value = false;
      requestId = '';
      void load();
    },
    { immediate: true }
  );
  watch([title, body], () => {
    confirmed.value = false;
    preview.value = false;
  });
</script>

<template>
  <section class="ticket-github" aria-label="GitHub 修复流程">
    <div class="github-toolbar">
      <strong>{{ state?.repository || 'GitHub 工作空间' }}</strong
      ><el-button :loading="busy" @click="load">刷新</el-button>
    </div>
    <el-alert
      v-if="error || state?.readback_error"
      :title="error || state?.readback_error"
      type="error"
      :closable="false"
    />
    <template v-if="state">
      <el-steps :active="step" simple
        ><el-step title="Issue" /><el-step title="云端修复" /><el-step title="PR 审查" /><el-step
          title="客户验收"
      /></el-steps>
      <el-alert
        v-if="!state.configured"
        title="GitHub 连接尚未配置"
        type="warning"
        :closable="false"
      />
      <el-alert
        v-if="!state.para_configured"
        title="GitHub 临时执行器尚未接通"
        type="warning"
        :closable="false"
      />
      <template v-if="state.issue">
        <div class="github-record">
          <span>问题记录</span
          ><a
            v-if="state.issue.url"
            :href="state.issue.url"
            target="_blank"
            rel="noopener noreferrer"
            >Issue #{{ state.issue.number }} ↗</a
          ><el-tag v-else type="warning">提交结果待核对</el-tag>
        </div>
        <div class="github-record">
          <span>执行状态</span
          ><a v-if="state.run?.url" :href="state.run.url" target="_blank" rel="noopener noreferrer"
            >{{ runLabel }} ↗</a
          ><span v-else>{{ runLabel }}</span>
        </div>
        <div v-for="job in state.jobs" :key="job.name" class="github-record">
          <span>{{ jobNames[job.name] || job.name }} · {{ job.employee_id }}</span
          ><el-tag
            :type="
              job.status === 'failed' ? 'danger' : job.conclusion === 'success' ? 'success' : 'info'
            "
            >{{ jobStates[job.conclusion || job.status] || job.status }}</el-tag
          >
        </div>
        <div v-for="pr in state.pulls" :key="pr.number" class="github-record">
          <span>修复结果</span
          ><a :href="pr.url" target="_blank" rel="noopener noreferrer"
            >PR #{{ pr.number }} ·
            {{
              pr.state === 'merged'
                ? '已合入，待发布验收'
                : pr.state === 'closed'
                  ? '已关闭'
                  : '待审查'
            }}
            ↗</a
          >
        </div>
        <el-alert
          v-if="state.issue.error || state.run?.error"
          :title="state.issue.error || state.run?.error"
          type="warning"
          :closable="false"
        />
        <div class="github-toolbar">
          <el-button
            type="primary"
            :disabled="
              !editable ||
              !state.configured ||
              !state.para_configured ||
              !state.issue.number ||
              !!state.run ||
              !!state.readback_error
            "
            :loading="busy"
            @click="start"
            >交给 AI 员工</el-button
          >
          <el-button
            :disabled="!state.configured"
            :loading="busy"
            @click="command('/reconcile', {})"
            >查询回执</el-button
          >
        </div>
        <p class="github-note">PR 合入后，仍需正式版本复测与原客户确认。</p>
      </template>
      <form
        v-else-if="editable"
        class="github-draft"
        @submit.prevent="command('', { title, body, confirm_public: confirmed })"
      >
        <label
          >公开标题<el-input v-model="title" maxlength="180" placeholder="填写可公开的技术问题"
        /></label>
        <label
          >公开技术摘要<el-input
            v-model="body"
            type="textarea"
            :rows="6"
            maxlength="10000"
            placeholder="复现步骤、预期结果、实际结果、验收条件"
        /></label>
        <el-button
          :disabled="title.trim().length < 5 || body.trim().length < 30"
          @click="preview = !preview"
          >{{ preview ? '收起预览' : '预览提交内容' }}</el-button
        >
        <div v-if="preview" class="github-preview">
          <strong>{{ title }}</strong>
          <pre>{{ body }}</pre>
        </div>
        <el-checkbox v-model="confirmed" :disabled="!preview"
          >确认发布到公开仓库，内容不含客户身份、凭据和附件</el-checkbox
        >
        <el-button
          native-type="submit"
          type="primary"
          :loading="busy"
          :disabled="!confirmed || !preview || !state.configured"
          >创建 GitHub Issue</el-button
        >
      </form>
      <el-empty v-else description="该工单已结束，暂无 GitHub 关联" :image-size="60" />
    </template>
  </section>
</template>

<style scoped>
  .ticket-github {
    display: flex;
    flex-direction: column;
    gap: 18px;
    min-width: 0;
  }
  .github-toolbar,
  .github-record {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
  }
  .github-record {
    padding: 14px 0;
    border-bottom: 1px solid var(--el-border-color-lighter);
  }
  .github-record > span:first-child,
  .github-note {
    color: var(--el-text-color-secondary);
    font-size: 13px;
  }
  .github-record a {
    color: var(--el-color-primary);
  }
  .github-draft {
    display: grid;
    gap: 14px;
  }
  .github-draft label {
    display: grid;
    gap: 6px;
    font-size: 13px;
  }
  .github-draft .el-checkbox {
    height: auto;
    white-space: normal;
  }
  .github-preview {
    padding: 14px;
    background: var(--el-fill-color-light);
    border-radius: 8px;
  }
  .github-preview pre {
    white-space: pre-wrap;
    overflow-wrap: anywhere;
    font: inherit;
  }
  .github-note {
    margin: 0;
  }
</style>
