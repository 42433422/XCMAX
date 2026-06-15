<template>
  <div v-if="visible" class="enterprise-update-bar" role="status">
    <span class="enterprise-update-bar__text">
      update 站有新版本
      <template v-if="hubVersion">（{{ hubVersion }}<template v-if="hubSha"> · {{ hubSha }}</template>）</template>
      ，请在企业端拉取更新。
    </span>
    <button type="button" class="btn btn-primary btn-sm" :disabled="applying" @click="openModal">
      {{ applying ? '更新中…' : '检查并更新' }}
    </button>
    <button type="button" class="enterprise-update-bar__dismiss" aria-label="稍后提醒" @click="dismiss">×</button>
  </div>

  <Modal v-model="modalOpen" title="企业端更新" max-width="520px">
    <div class="enterprise-update-modal">
      <div class="enterprise-update-pipeline muted">
        管理端已推送到 update 站 → 本机从此拉取并应用
      </div>
      <table v-if="checkData" class="enterprise-update-table">
        <tbody>
          <tr>
            <th>update 站</th>
            <td>{{ checkData.update_hub.git_sha || '—' }}</td>
          </tr>
          <tr>
            <th>本机已部署</th>
            <td>{{ checkData.enterprise.deployed_sha256?.slice(0, 12) || '—' }}</td>
          </tr>
        </tbody>
      </table>
      <ol v-if="jobSteps.length" class="enterprise-update-steps">
        <li v-for="step in jobSteps" :key="step.id" :class="`is-${step.status}`">
          {{ step.label }}
          <span v-if="step.detail" class="muted"> — {{ step.detail }}</span>
        </li>
      </ol>
      <p v-if="jobError" class="enterprise-update-error">{{ jobError }}</p>
    </div>
    <template #footer>
      <button type="button" class="btn btn-secondary btn-sm" :disabled="applying" @click="modalOpen = false">
        关闭
      </button>
      <button type="button" class="btn btn-primary btn-sm" :disabled="applying" @click="runApply">
        {{ applying ? '拉取中…' : '立即更新' }}
      </button>
    </template>
  </Modal>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import Modal from '@/components/Modal.vue';
import { isAdminConsoleSpa } from '@/utils/adminConsoleUrl';
import {
  xcmaxDeployApi,
  type DeployJobData,
  type EnterpriseDeployCheck,
} from '@/api/xcmaxDeploy';

const DISMISS_KEY = 'xcagi_enterprise_update_dismiss_sha';

const visible = ref(false);
const modalOpen = ref(false);
const applying = ref(false);
const checkData = ref<EnterpriseDeployCheck | null>(null);
const jobSteps = ref<DeployJobData['steps']>([]);
const jobError = ref('');
let pollTimer: number | null = null;

const hubVersion = computed(() => checkData.value?.update_hub?.version || '');
const hubSha = computed(() => checkData.value?.update_hub?.git_sha || '');

function stopPoll() {
  if (pollTimer != null) {
    window.clearInterval(pollTimer);
    pollTimer = null;
  }
}

async function refreshCheck() {
  if (isAdminConsoleSpa()) return;
  try {
    const res = (await xcmaxDeployApi.checkEnterpriseUpdates()) as { data?: EnterpriseDeployCheck };
    checkData.value = res?.data || null;
    const hubShaVal = res?.data?.update_hub?.sha256 || '';
    const dismissed = sessionStorage.getItem(DISMISS_KEY) || '';
    visible.value = Boolean(res?.data?.flags?.needs_update && hubShaVal && hubShaVal !== dismissed);
  } catch {
    visible.value = false;
  }
}

function dismiss() {
  const sha = checkData.value?.update_hub?.sha256 || '';
  if (sha) sessionStorage.setItem(DISMISS_KEY, sha);
  visible.value = false;
}

function openModal() {
  modalOpen.value = true;
  jobSteps.value = [];
  jobError.value = '';
}

async function pollJob(jobId: string) {
  stopPoll();
  pollTimer = window.setInterval(async () => {
    try {
      const res = (await xcmaxDeployApi.getEnterpriseJob(jobId)) as { data?: DeployJobData };
      const job = res?.data;
      if (!job) return;
      jobSteps.value = job.steps || [];
      if (job.status === 'done') {
        applying.value = false;
        stopPoll();
        await refreshCheck();
      } else if (job.status === 'error') {
        applying.value = false;
        jobError.value = job.error || '更新失败';
        stopPoll();
      }
    } catch (e) {
      applying.value = false;
      jobError.value = e instanceof Error ? e.message : String(e);
      stopPoll();
    }
  }, 1200);
}

async function runApply() {
  applying.value = true;
  jobError.value = '';
  try {
    const res = (await xcmaxDeployApi.applyEnterpriseUpdate()) as {
      data?: DeployJobData;
      message?: string;
    };
    const jobId = res?.data?.job_id;
    if (!jobId) throw new Error(res?.message || '未收到任务 ID');
    jobSteps.value = res.data?.steps || [];
    await pollJob(jobId);
  } catch (e) {
    applying.value = false;
    jobError.value = e instanceof Error ? e.message : String(e);
  }
}

onMounted(() => {
  void refreshCheck();
});

onBeforeUnmount(() => {
  stopPoll();
});
</script>

<style scoped>
.enterprise-update-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin: 0 0 10px;
  padding: 10px 14px;
  border-radius: 8px;
  background: #eff6ff;
  border: 1px solid #bfdbfe;
  color: #1e3a8a;
  font-size: 13px;
}

.enterprise-update-bar__text {
  flex: 1;
  min-width: 200px;
}

.enterprise-update-bar__dismiss {
  border: none;
  background: transparent;
  font-size: 18px;
  line-height: 1;
  cursor: pointer;
  color: #64748b;
}

.enterprise-update-pipeline {
  font-size: 13px;
  margin-bottom: 12px;
}

.enterprise-update-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
  margin-bottom: 12px;
}

.enterprise-update-table th,
.enterprise-update-table td {
  border: 1px solid #e5e7eb;
  padding: 8px 10px;
  text-align: left;
}

.enterprise-update-steps {
  margin: 0;
  padding-left: 18px;
  font-size: 13px;
}

.enterprise-update-steps .is-running {
  color: #0369a1;
}

.enterprise-update-steps .is-done {
  color: #15803d;
}

.enterprise-update-steps .is-error {
  color: #b91c1c;
}

.enterprise-update-error {
  margin-top: 10px;
  color: #991b1b;
  font-size: 13px;
}
</style>
