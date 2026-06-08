<template>
  <div
    class="contract-esign-panel cs-esign-panel"
    :class="{ 'contract-esign-panel--compact': compact }"
  >
    <header v-if="showTitle && !compact" class="contract-esign-panel__head">
      <h3 class="contract-esign-panel__title">电子签章</h3>
      <span v-if="stageLabel" class="contract-esign-panel__stage">{{ stageLabel }}</span>
    </header>
    <p class="contract-esign-panel__hint">
      法大大 / Stub 适配器；签署完成 webhook 可将商机阶段推进为「已签约」。
    </p>

    <p v-if="!marketUserId" class="contract-esign-panel__empty muted">
      {{ emptyHint }}
    </p>

    <template v-else>
      <p v-if="loading" class="muted">加载签章状态…</p>
      <p v-else-if="loadError" class="contract-esign-panel__error">{{ loadError }}</p>

      <template v-else>
        <dl class="contract-esign-panel__dl">
          <dt>合同状态</dt>
          <dd>{{ lifecycle?.status || '—' }}</dd>
          <dt>签章任务</dt>
          <dd>{{ lifecycle?.esign_ref || taskId || '—' }}</dd>
          <dt>提供商</dt>
          <dd>{{ lifecycle?.esign_provider || '—' }}</dd>
          <template v-if="erpCustomerName">
            <dt>客户</dt>
            <dd>{{ erpCustomerName }}</dd>
          </template>
        </dl>

        <label v-if="allowPartyAEdit" class="contract-esign-panel__field">
          <span>甲方（签署方）</span>
          <input v-model="partyAInput" type="text" class="form-control" placeholder="公司全称">
        </label>

        <div class="contract-esign-panel__actions">
          <button
            type="button"
            class="btn btn-primary btn-sm"
            :disabled="starting || !marketUserId"
            @click="onStart"
          >
            {{ starting ? '发起中…' : '发起电子签' }}
          </button>
          <button
            v-if="signUrl"
            type="button"
            class="btn btn-secondary btn-sm"
            @click="copySignUrl"
          >
            复制签署链接
          </button>
          <a
            v-if="signUrl"
            class="btn btn-secondary btn-sm"
            :href="signUrl"
            target="_blank"
            rel="noopener noreferrer"
          >
            打开签署页
          </a>
          <select v-model="transitionStatus" class="form-control contract-esign-panel__select">
            <option value="">手动纠偏状态</option>
            <option value="sent">已发送</option>
            <option value="signing">签署中</option>
            <option value="effective">已生效</option>
          </select>
          <button
            type="button"
            class="btn btn-secondary btn-sm"
            :disabled="!transitionStatus || transitioning"
            @click="onTransition"
          >
            {{ transitioning ? '保存中…' : '应用状态' }}
          </button>
          <button
            type="button"
            class="btn btn-secondary btn-sm"
            :disabled="loading"
            @click="reload"
          >
            刷新
          </button>
        </div>
        <p v-if="actionMessage" class="contract-esign-panel__msg" :class="{ 'is-error': actionError }">
          {{ actionMessage }}
        </p>
      </template>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import {
  fetchContractLifecycleStatus,
  startContractEsign,
  transitionContractLifecycle,
  type ContractLifecycleBlock,
} from '@/api/contractLifecycle';

const STAGE_LABELS: Record<string, string> = {
  idle: '未接触',
  connected: '已建联',
  intake: '需求采集',
  intake_done: '需求已提交',
  quoted: '已报价',
  negotiating: '议价中',
  contract_pending: '待签约',
  signed: '已签约',
  delivering: '交付中',
  delivered: '已交付',
};

const props = withDefaults(
  defineProps<{
    marketUserId?: number | null;
    username?: string;
    partyA?: string;
    compact?: boolean;
    showTitle?: boolean;
    allowPartyAEdit?: boolean;
    emptyHint?: string;
  }>(),
  {
    marketUserId: null,
    username: '',
    partyA: '',
    compact: false,
    showTitle: true,
    allowPartyAEdit: true,
    emptyHint: '请先填写或选择市场用户 ID',
  },
);

const emit = defineEmits<{
  updated: [pipeline: Record<string, unknown>];
}>();

const loading = ref(false);
const loadError = ref('');
const starting = ref(false);
const transitioning = ref(false);
const transitionStatus = ref('');
const actionMessage = ref('');
const actionError = ref(false);

const lifecycle = ref<ContractLifecycleBlock | null>(null);
const pipelineStage = ref('');
const erpCustomerName = ref('');
const signUrl = ref('');
const taskId = ref('');
const partyAInput = ref('');

const stageLabel = computed(() => {
  const id = pipelineStage.value;
  return id ? STAGE_LABELS[id] || id : '';
});

function applyStatus(data: Awaited<ReturnType<typeof fetchContractLifecycleStatus>>) {
  pipelineStage.value = String(data.stage || '');
  erpCustomerName.value = String(data.erp_customer_name || '');
  lifecycle.value = data.contract_lifecycle || null;
  const task = data.contract_lifecycle?.esign_task;
  taskId.value = String(data.contract_lifecycle?.esign_ref || task?.task_id || '');
  signUrl.value = String(data.sign_url || task?.sign_url || '').trim();
  if (!partyAInput.value && (props.partyA || data.party_a_default)) {
    partyAInput.value = props.partyA || data.party_a_default || '';
  }
}

async function reload() {
  const uid = Number(props.marketUserId || 0);
  if (uid <= 0) {
    lifecycle.value = null;
    loadError.value = '';
    return;
  }
  loading.value = true;
  loadError.value = '';
  actionMessage.value = '';
  try {
    const data = await fetchContractLifecycleStatus(uid, props.username || '');
    applyStatus(data);
  } catch (e) {
    loadError.value = e instanceof Error ? e.message : String(e);
  } finally {
    loading.value = false;
  }
}

async function onStart() {
  const uid = Number(props.marketUserId || 0);
  if (uid <= 0) return;
  starting.value = true;
  actionMessage.value = '';
  actionError.value = false;
  try {
    const pipeline = await startContractEsign({
      market_user_id: uid,
      username: props.username || '',
      party_a: partyAInput.value || props.partyA || erpCustomerName.value,
    });
    emit('updated', pipeline);
    await reload();
    actionMessage.value = '电子签任务已创建';
  } catch (e) {
    actionError.value = true;
    actionMessage.value = e instanceof Error ? e.message : '发起失败';
  } finally {
    starting.value = false;
  }
}

async function onTransition() {
  const uid = Number(props.marketUserId || 0);
  if (uid <= 0 || !transitionStatus.value) return;
  transitioning.value = true;
  actionMessage.value = '';
  actionError.value = false;
  try {
    const pipeline = await transitionContractLifecycle({
      market_user_id: uid,
      status: transitionStatus.value,
      username: props.username || '',
    });
    emit('updated', pipeline);
    transitionStatus.value = '';
    await reload();
    actionMessage.value = '合同状态已更新';
  } catch (e) {
    actionError.value = true;
    actionMessage.value = e instanceof Error ? e.message : '更新失败';
  } finally {
    transitioning.value = false;
  }
}

async function copySignUrl() {
  if (!signUrl.value) return;
  try {
    await navigator.clipboard.writeText(signUrl.value);
    actionMessage.value = '已复制签署链接';
    actionError.value = false;
  } catch {
    actionMessage.value = signUrl.value;
    actionError.value = false;
  }
}

watch(
  () => [props.marketUserId, props.username] as const,
  () => {
    if (props.partyA) partyAInput.value = props.partyA;
    void reload();
  },
  { immediate: true },
);

watch(
  () => props.partyA,
  (v) => {
    if (v) partyAInput.value = v;
  },
);
</script>

<style scoped>
.contract-esign-panel {
  padding: 14px 16px;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  background: #fff;
}
.contract-esign-panel--compact {
  padding: 12px 14px;
}
.contract-esign-panel__head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 6px;
}
.contract-esign-panel__title {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
}
.contract-esign-panel__stage {
  font-size: 12px;
  color: #64748b;
  padding: 2px 8px;
  border-radius: 999px;
  background: #f1f5f9;
}
.contract-esign-panel__hint {
  margin: 0 0 12px;
  font-size: 12px;
  color: #64748b;
  line-height: 1.45;
}
.contract-esign-panel__dl {
  display: grid;
  grid-template-columns: 88px 1fr;
  gap: 6px 12px;
  margin: 0 0 12px;
  font-size: 13px;
}
.contract-esign-panel__dl dt {
  margin: 0;
  color: #64748b;
}
.contract-esign-panel__dl dd {
  margin: 0;
}
.contract-esign-panel__field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-bottom: 12px;
  font-size: 13px;
}
.contract-esign-panel__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}
.contract-esign-panel__select {
  width: auto;
  min-width: 140px;
  max-width: 200px;
}
.contract-esign-panel__error {
  color: #b45309;
  font-size: 13px;
}
.contract-esign-panel__msg {
  margin: 10px 0 0;
  font-size: 12px;
  color: #15803d;
}
.contract-esign-panel__msg.is-error {
  color: #b91c1c;
}
.contract-esign-panel__empty {
  margin: 0;
  font-size: 13px;
}
</style>
