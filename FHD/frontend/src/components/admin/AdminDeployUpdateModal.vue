<template>
  <Modal
    :model-value="modelValue"
    title="推送到 update 中转站"
    max-width="560px"
    @update:model-value="$emit('update:modelValue', $event)"
    @close="$emit('update:modelValue', false)"
  >
    <div class="deploy-update-modal">
      <p class="deploy-update-modal__intro muted">
        管理端只负责<strong>推</strong>到 update 站；企业端在 :5001 自行<strong>收</strong>（拉取并应用）。
      </p>

      <div v-if="checkData && !checkLoading" class="deploy-update-pipeline" aria-hidden="true">
        <span class="deploy-update-pipeline__node is-admin">管理端<br><small>推</small></span>
        <span class="deploy-update-pipeline__arrow">→</span>
        <span class="deploy-update-pipeline__node is-hub">update 站<br><small>中转</small></span>
        <span class="deploy-update-pipeline__arrow">→</span>
        <span class="deploy-update-pipeline__node is-ent">企业端<br><small>收</small></span>
      </div>

      <div v-if="checkLoading" class="deploy-update-modal__checking">正在检测更新…</div>
      <div v-else-if="checkError" class="deploy-update-alert" role="alert">{{ checkError }}</div>

      <table v-if="checkData && !checkLoading" class="deploy-update-table">
        <thead>
          <tr>
            <th>来源</th>
            <th>版本</th>
            <th>Git</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>① 管理端本地</td>
            <td>{{ checkData.admin_local.version }}</td>
            <td><code>{{ checkData.admin_local.git_sha }}</code></td>
          </tr>
          <tr>
            <td>② update 中转站</td>
            <td>{{ checkData.update_hub.version || '—' }}</td>
            <td><code>{{ checkData.update_hub.git_sha || '—' }}</code></td>
          </tr>
          <tr>
            <td>③ 企业运行态（只读）</td>
            <td>{{ checkData.enterprise.reachable ? (checkData.enterprise.version || '—') : '不可达' }}</td>
            <td><code>{{ checkData.enterprise.deploy_sha256?.slice(0, 12) || '—' }}</code></td>
          </tr>
        </tbody>
      </table>

      <div v-if="statusBanner" class="deploy-update-banner" :class="statusBanner.kind">
        {{ statusBanner.text }}
      </div>

      <details class="deploy-update-custom" :open="customOpen">
        <summary>定制更新内容</summary>
        <label class="deploy-update-check">
          <input v-model="opts.include_backend" type="checkbox" :disabled="pushing">
          后端（打包 + 上传 update 站）
        </label>
        <label class="deploy-update-check">
          <input v-model="opts.include_frontend" type="checkbox" :disabled="pushing">
          前端（构建 vue-dist + 发布到 update 站）
        </label>
        <label class="deploy-update-check">
          <input v-model="opts.skip_pack" type="checkbox" :disabled="pushing || !opts.include_backend">
          跳过后端打包（使用已有 dist/deploy 产物）
        </label>
        <label class="deploy-update-field">
          <span>发布通道</span>
          <select v-model="opts.channel" :disabled="pushing">
            <option value="stable">stable（生产）</option>
            <option value="staging">staging（预发）</option>
          </select>
        </label>
      </details>

      <ol v-if="jobSteps.length" class="deploy-update-steps">
        <li
          v-for="step in jobSteps"
          :key="step.id"
          :class="['deploy-update-step', `is-${step.status}`]"
        >
          <span class="deploy-update-step__icon" aria-hidden="true">{{ stepIcon(step.status) }}</span>
          <span class="deploy-update-step__label">{{ step.label }}</span>
          <span v-if="step.detail" class="deploy-update-step__detail muted">{{ step.detail }}</span>
        </li>
      </ol>

      <p v-if="jobError" class="deploy-update-alert" role="alert">{{ jobError }}</p>
    </div>

    <template #footer>
      <button type="button" class="btn btn-secondary btn-sm" :disabled="pushing" @click="close">
        关闭
      </button>
      <button
        type="button"
        class="btn btn-secondary btn-sm"
        :disabled="checkLoading || pushing"
        @click="runCheck"
      >
        重新检测
      </button>
      <button
        type="button"
        class="btn btn-primary btn-sm"
        :disabled="checkLoading || pushing || !canPush"
        @click="startPush(false)"
      >
        {{ pushing ? '推送中…' : '推送到 update 站' }}
      </button>
      <button
        type="button"
        class="btn btn-primary btn-sm"
        :disabled="checkLoading || pushing || !canPush"
        @click="startPush(true)"
      >
        定制推送
      </button>
    </template>
  </Modal>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import Modal from '@/components/Modal.vue';
import { xcmaxAdminApi, type DeployCheckData, type DeployJobData } from '@/api/xcmaxAdmin';

const props = defineProps<{ modelValue: boolean }>();
const emit = defineEmits<{ 'update:modelValue': [boolean]; done: [] }>();

const checkLoading = ref(false);
const checkError = ref('');
const checkData = ref<DeployCheckData | null>(null);
const customOpen = ref(false);
const pushing = ref(false);
const jobSteps = ref<DeployJobData['steps']>([]);
const jobError = ref('');
const pollTimer = ref<number | null>(null);

const opts = ref({
  include_backend: true,
  include_frontend: true,
  skip_pack: false,
  channel: 'stable' as 'stable' | 'staging',
});

const statusBanner = computed(() => {
  const d = checkData.value;
  if (!d) return null;
  const f = d.flags;
  if (f.up_to_date && !f.enterprise_pending) {
    return { kind: 'ok', text: '管理端与 update 站已同步；若企业端未更新，请通知企业在 :5001 点击「检查并更新」。' };
  }
  if (f.needs_push) {
    return { kind: 'warn', text: '发现新版本：请推送到 update 中转站（不会直连企业机）。' };
  }
  if (f.enterprise_pending) {
    return {
      kind: 'info',
      text: 'update 站已有新包，企业端待拉取（cron 约 5 分钟，或企业用户在界面手动更新）。',
    };
  }
  if (f.needs_pack) {
    return { kind: 'warn', text: '本地尚未打包，推送时将自动 pack。' };
  }
  return null;
});

const canPush = computed(() => opts.value.include_backend || opts.value.include_frontend);

function stepIcon(status: string) {
  if (status === 'done') return '✓';
  if (status === 'running') return '…';
  if (status === 'error') return '✕';
  if (status === 'skipped') return '−';
  return '○';
}

function stopPoll() {
  if (pollTimer.value != null) {
    window.clearInterval(pollTimer.value);
    pollTimer.value = null;
  }
}

async function runCheck() {
  checkLoading.value = true;
  checkError.value = '';
  try {
    const res = (await xcmaxAdminApi.checkDeployUpdates()) as { data?: DeployCheckData; message?: string };
    if (!res?.data) throw new Error(res?.message || '检测失败');
    checkData.value = res.data;
  } catch (e) {
    checkError.value = e instanceof Error ? e.message : String(e);
    checkData.value = null;
  } finally {
    checkLoading.value = false;
  }
}

async function pollJob(jobId: string) {
  stopPoll();
  pollTimer.value = window.setInterval(async () => {
    try {
      const res = (await xcmaxAdminApi.getDeployJob(jobId)) as { data?: DeployJobData };
      const job = res?.data;
      if (!job) return;
      jobSteps.value = job.steps || [];
      if (job.status === 'done') {
        pushing.value = false;
        jobError.value = '';
        stopPoll();
        await runCheck();
        emit('done');
      } else if (job.status === 'error') {
        pushing.value = false;
        jobError.value = job.error || '推送失败';
        stopPoll();
      }
    } catch (e) {
      pushing.value = false;
      jobError.value = e instanceof Error ? e.message : String(e);
      stopPoll();
    }
  }, 1200);
}

async function startPush(openCustom: boolean) {
  if (openCustom) customOpen.value = true;
  pushing.value = true;
  jobError.value = '';
  jobSteps.value = [];
  try {
    const res = (await xcmaxAdminApi.startDeployPush({ ...opts.value })) as {
      data?: DeployJobData;
      message?: string;
    };
    const jobId = res?.data?.job_id;
    if (!jobId) throw new Error(res?.message || '未收到任务 ID');
    jobSteps.value = res.data?.steps || [];
    await pollJob(jobId);
  } catch (e) {
    pushing.value = false;
    jobError.value = e instanceof Error ? e.message : String(e);
  }
}

function close() {
  if (pushing.value) return;
  emit('update:modelValue', false);
}

watch(
  () => props.modelValue,
  (open) => {
    if (open) {
      customOpen.value = false;
      jobSteps.value = [];
      jobError.value = '';
      void runCheck();
    } else {
      stopPoll();
    }
  },
);
</script>

<style scoped>
.deploy-update-modal__intro {
  margin: 0 0 12px;
  font-size: 13px;
  line-height: 1.5;
}

.deploy-update-pipeline {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  margin-bottom: 14px;
  padding: 10px;
  border-radius: 8px;
  background: #f8fafc;
  border: 1px dashed #cbd5e1;
}

.deploy-update-pipeline__node {
  text-align: center;
  font-size: 12px;
  font-weight: 600;
  padding: 6px 10px;
  border-radius: 8px;
  min-width: 72px;
}

.deploy-update-pipeline__node small {
  font-weight: 500;
  opacity: 0.75;
}

.deploy-update-pipeline__node.is-admin {
  background: #dbeafe;
  color: #1d4ed8;
}

.deploy-update-pipeline__node.is-hub {
  background: #fef3c7;
  color: #92400e;
}

.deploy-update-pipeline__node.is-ent {
  background: #dcfce7;
  color: #166534;
}

.deploy-update-pipeline__arrow {
  color: #94a3b8;
  font-weight: 700;
}

.deploy-update-modal__checking {
  padding: 12px 0;
  color: #475569;
  font-size: 14px;
}

.deploy-update-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
  margin-bottom: 12px;
}

.deploy-update-table th,
.deploy-update-table td {
  border: 1px solid #e5e7eb;
  padding: 8px 10px;
  text-align: left;
}

.deploy-update-table th {
  background: #f8fafc;
  font-weight: 600;
}

.deploy-update-table code {
  font-size: 12px;
}

.deploy-update-banner {
  padding: 10px 12px;
  border-radius: 8px;
  font-size: 13px;
  margin-bottom: 12px;
}

.deploy-update-banner.is-ok {
  background: #ecfdf5;
  color: #065f46;
  border: 1px solid #a7f3d0;
}

.deploy-update-banner.is-warn {
  background: #fffbeb;
  color: #92400e;
  border: 1px solid #fde68a;
}

.deploy-update-banner.is-info {
  background: #eff6ff;
  color: #1e40af;
  border: 1px solid #bfdbfe;
}

.deploy-update-custom {
  margin: 12px 0;
  font-size: 13px;
}

.deploy-update-custom summary {
  cursor: pointer;
  font-weight: 600;
  margin-bottom: 8px;
}

.deploy-update-check {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 6px 0;
}

.deploy-update-field {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 8px;
}

.deploy-update-field select {
  min-height: 32px;
  border-radius: 6px;
  border: 1px solid #e5e7eb;
  padding: 0 8px;
}

.deploy-update-steps {
  list-style: none;
  margin: 14px 0 0;
  padding: 0;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  overflow: hidden;
}

.deploy-update-step {
  display: grid;
  grid-template-columns: 24px 1fr;
  gap: 4px 8px;
  padding: 10px 12px;
  border-bottom: 1px solid #f1f5f9;
  font-size: 13px;
}

.deploy-update-step:last-child {
  border-bottom: none;
}

.deploy-update-step.is-running {
  background: #f0f9ff;
}

.deploy-update-step.is-done .deploy-update-step__icon {
  color: #15803d;
}

.deploy-update-step.is-error {
  background: #fef2f2;
}

.deploy-update-step.is-error .deploy-update-step__icon {
  color: #b91c1c;
}

.deploy-update-step__detail {
  grid-column: 2;
  font-size: 12px;
  word-break: break-all;
}

.deploy-update-alert {
  margin-top: 10px;
  padding: 10px 12px;
  border-radius: 8px;
  background: #fef2f2;
  color: #991b1b;
  border: 1px solid #fecaca;
  font-size: 13px;
}
</style>
