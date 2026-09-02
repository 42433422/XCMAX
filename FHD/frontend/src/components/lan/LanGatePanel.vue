<template>
  <div
    class="lan-gate-panel"
    :class="{
      blocked: !inWhitelist && enabled,
      'pending-user-key': enabled && inWhitelist && !showKeyForm,
      'is-modal': variant === 'modal'
    }"
  >
    <div v-if="variant === 'modal'" class="lan-gate-modal-bar">
      <span class="lan-gate-modal-title">局域网授权</span>
      <button type="button" class="btn-text" @click="onDismiss">稍后再说</button>
    </div>
    <div class="card">
      <div v-if="variant === 'page'" class="brand">
        <i class="fa fa-shield-alt"></i>
        <h1>FHD · 局域网授权</h1>
      </div>
      <div v-else class="brand brand-compact">
        <i class="fa fa-shield-alt"></i>
        <h1>局域网授权</h1>
      </div>

      <div v-if="!enabled" class="state-banner ok">
        <i class="fa fa-info-circle"></i>
        <span>当前未启用局域网模式，无需授权。</span>
        <button class="btn primary" @click="goHomeFromButton">进入系统</button>
      </div>

      <div v-else-if="needsGateWait" class="gate-wait">
        <div class="state-banner" :class="!inWhitelist ? 'danger' : 'warn'">
          <i class="fa" :class="!inWhitelist ? 'fa-ban' : 'fa-hourglass-half'"></i>
          <div>
            <template v-if="!inWhitelist">
              <strong>非授权网络</strong>
              <p>当前 IP <code>{{ ip || '未知' }}</code> 不在许可网段内，站点访问将被拦截。</p>
              <p class="muted">提交申请，待管理员批准后再用密钥。</p>
            </template>
            <template v-else>
              <strong>普通密钥须先经审批</strong>
              <p>
                本机 <code>{{ ip || '—' }}</code> 已在许可网段内，但使用<strong>普通（非管理员）密钥</strong>前，必须由管理员在主机控制台批准访问申请（本机 IP 进入动态白名单）。
              </p>
              <p class="muted">批准后点「重新检测」，或用管理员密钥。</p>
            </template>
          </div>
        </div>
        <div class="request-box">
          <template v-if="accessRequest">
            <div class="request-state" :class="accessRequest.status">
              <strong>当前申请状态：{{ requestStatusText }}</strong>
              <p v-if="accessRequest.device_label">设备：{{ accessRequest.device_label }}</p>
              <p v-if="accessRequest.review_note">处理备注：{{ accessRequest.review_note }}</p>
            </div>
          </template>
          <form class="form request-form" @submit.prevent="submitAccessRequest">
            <label>
              设备名称
              <input
                v-model="requestForm.device_label"
                maxlength="200"
                :disabled="requestForm.submitting"
                placeholder="如：财务室-PC3 / 张三笔记本"
              />
            </label>
            <label>
              申请说明
              <input
                v-model="requestForm.note"
                maxlength="500"
                :disabled="requestForm.submitting"
                placeholder="可选，例如所在部门、用途"
              />
            </label>
            <div class="request-actions">
              <button class="btn primary" type="submit" :disabled="requestForm.submitting">
                <i class="fa fa-paper-plane"></i>
                {{ requestForm.submitting ? '正在提交…' : (accessRequest?.status === 'pending' ? '更新申请' : '提交访问申请') }}
              </button>
              <button class="btn" type="button" @click="load" :disabled="requestForm.submitting">
                <i class="fa fa-sync"></i> 重新检测
              </button>
            </div>
          </form>
        </div>
        <div class="admin-key-entry">
          <button type="button" class="btn ghost wide" @click="unlockAdminKey">
            <i class="fa fa-user-shield"></i> 持有管理员密钥？点此输入
          </button>
        </div>
      </div>

      <template v-else>
        <p v-if="adminKeyUnlocked && !userKeyClearance && !bootstrapAvailable" class="lead warn-lead">
          当前为<strong>管理员密钥</strong>入口。普通密钥在管理员批准本机 IP 前无法激活。
        </p>
        <p class="lead">
          <template v-if="userKeyClearance || bootstrapAvailable">
            本机 <code>{{ ip || '—' }}</code> 已获准使用普通密钥，请输入<strong>一级密钥</strong>完成授权。授权后约 {{ ttlHours }} 小时内无需重复输入。
          </template>
          <template v-else>
            请输入<strong>管理员级一级密钥</strong>（或引导密钥）完成本机授权。授权后约 {{ ttlHours }} 小时内无需重复输入。
          </template>
        </p>

        <form class="form" @submit.prevent="submit">
          <label>
            一级密钥
            <input
              v-model="keyInput"
              type="password"
              autocomplete="off"
              :autofocus="variant === 'page'"
              :disabled="submitting"
              placeholder="向管理员索取，或使用引导密钥"
            />
          </label>
          <label v-if="bootstrapAvailable">
            备注（可选；仅引导密钥首次激活时使用）
            <input v-model="labelInput" maxlength="100" placeholder="如：财务老李 / PC-3" />
          </label>

          <button class="btn primary big" type="submit" :disabled="submitting || !keyInput">
            <i class="fa fa-key"></i>
            {{ submitting ? '正在校验…' : '激活本机' }}
          </button>
        </form>

        <div v-if="bootstrapAvailable" class="hint-box">
          <i class="fa fa-magic"></i>
          检测到尚未签发任何密钥。本次输入的若是 <code>LAN_ADMIN_BOOTSTRAP_KEY</code>，
          会自动登记为 <strong>管理员级</strong> 密钥并开启控制台。
        </div>

        <div v-if="errorMsg" class="error">
          <i class="fa fa-times-circle"></i> {{ errorMsg }}
        </div>
      </template>

      <footer class="meta">
        <span>状态：{{ enabled ? '局域网授权已启用' : '未启用' }}</span>
        <span v-if="ip">本机 IP：<code>{{ ip }}</code></span>
        <span v-if="isAdminHost">主机管理员位</span>
      </footer>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, reactive } from 'vue';
import { useRouter } from 'vue-router';
import { lanGateApi, type AccessRequestEntry, type LanHostInfo } from '@/api/lanGate';
import { useLanGate } from '@/composables/useLanGate';
import { useModsStore } from '@/stores/mods';
import { asRecord, asString } from '@/utils/typeGuards'
import { ApiError } from '@/api/core'

function errorDetail(e: unknown, fallback = ''): string {
  if (e instanceof ApiError) {
    const data = asRecord(e.data)
    return asString(data.detail || data.message || e.message, fallback)
  }
  if (e instanceof Error) return e.message
  return asString(e, fallback)
}

const props = withDefaults(
  defineProps<{
    variant?: 'page' | 'modal';
    redirectPath?: string;
  }>(),
  {
    variant: 'page',
    redirectPath: '/'
  }
);

const router = useRouter();
const { refresh, status, dismissLanGateModal } = useLanGate();
const modsStore = useModsStore();

const keyInput = ref('');
const labelInput = ref('');
const submitting = ref(false);
const errorMsg = ref('');
const hostInfo = ref<LanHostInfo | null>(null);
const accessRequest = ref<AccessRequestEntry | null>(null);
const requestForm = reactive({
  device_label: '',
  note: '',
  submitting: false
});

const enabled = computed(() => status.value?.enabled ?? false);
const inWhitelist = computed(() => status.value?.in_whitelist ?? false);
const userKeyClearance = computed(() => status.value?.in_dynamic_allowlist ?? false);
const bootstrapAvailable = computed(() => hostInfo.value?.bootstrap_available ?? false);
const adminKeyUnlocked = ref(false);
const showKeyForm = computed(
  () => userKeyClearance.value || adminKeyUnlocked.value || bootstrapAvailable.value
);
const needsGateWait = computed(() => enabled.value && !showKeyForm.value);
const isAdminHost = computed(() => status.value?.is_admin_host ?? false);
const ip = computed(() => status.value?.ip ?? '');
const ttlHours = computed(() => Math.round((hostInfo.value?.token_ttl_seconds || 28800) / 3600));
const requestStatusText = computed(() => {
  if (!accessRequest.value) return '未提交';
  switch (accessRequest.value.status) {
    case 'approved':
      return '已批准，请点击“重新检测”后继续输入一级密钥';
    case 'rejected':
      return '已拒绝，可修改信息后重新提交';
    default:
      return '待管理员审核';
  }
});

const redirect = computed(() => (props.redirectPath && props.redirectPath.trim()) || '/');

function onDismiss() {
  if (props.variant === 'modal') {
    dismissLanGateModal();
  }
}

function unlockAdminKey() {
  adminKeyUnlocked.value = true;
}

async function load() {
  try {
    await refresh(true);
    hostInfo.value = await lanGateApi.hostInfo();
    if (status.value?.enabled && !status.value?.in_dynamic_allowlist) {
      const mine = await lanGateApi.myAccessRequest();
      accessRequest.value = mine.request || null;
      if (accessRequest.value?.device_label && !requestForm.device_label) {
        requestForm.device_label = accessRequest.value.device_label;
      }
      if (accessRequest.value?.note && !requestForm.note) {
        requestForm.note = accessRequest.value.note;
      }
    } else {
      accessRequest.value = null;
    }
    if (status.value?.authorized) {
      await goHome(false);
    }
  } catch (e: unknown) {
    errorMsg.value = `初始化失败：${errorDetail(e, '未知错误')}`;
  }
}

async function submitAccessRequest() {
  if (requestForm.submitting) return;
  errorMsg.value = '';
  requestForm.submitting = true;
  try {
    const r = await lanGateApi.requestAccess({
      device_label: requestForm.device_label.trim(),
      note: requestForm.note.trim()
    });
    accessRequest.value = r.request || null;
  } catch (e: unknown) {
    const detail = errorDetail(e, '提交申请失败');
    errorMsg.value = mapError(detail);
  } finally {
    requestForm.submitting = false;
  }
}

async function submit() {
  if (submitting.value) return;
  errorMsg.value = '';
  submitting.value = true;
  try {
    const r = await lanGateApi.activate(keyInput.value.trim(), labelInput.value.trim() || undefined);
    if (r?.success) {
      keyInput.value = '';
      await refresh(true);
      await goHome(r.is_admin);
    } else {
      errorMsg.value = '激活失败';
    }
  } catch (e: unknown) {
    const detail = errorDetail(e, '激活失败');
    errorMsg.value = mapError(detail);
  } finally {
    submitting.value = false;
  }
}

function mapError(detail: string): string {
  switch (detail) {
    case 'bad_key':
      return '密钥错误，请检查后重试';
    case 'key_revoked':
      return '该密钥已被吊销';
    case 'key_expired':
      return '该密钥已过期';
    case 'lan_blocked':
      return '当前 IP 不在白名单网段';
    case 'activation_requires_approval':
      return '普通密钥须管理员批准本机 IP 后才能激活，请等待审批或使用管理员密钥';
    case 'license_misconfigured':
      return '服务端 LAN_LICENSE_SECRET 未配置';
    case 'lan_mode_disabled':
      return '服务端尚未启用局域网模式';
    case 'admin_host_required':
      return '该操作仅允许管理员主机直接执行';
    case 'empty_key':
      return '请输入密钥';
    default:
      return String(detail);
  }
}

async function goHome(adminAfter = false) {
  const r = redirect.value;
  if (adminAfter && r === '/') {
    await modsStore.initialize();
    const hasRoute = router.getRoutes().some((rt) => rt.path === '/qsm-pro');
    await router.replace(hasRoute ? '/qsm-pro' : '/');
  } else {
    await router.replace(r);
  }
  if (props.variant === 'modal') {
    dismissLanGateModal();
  }
}

function goHomeFromButton() {
  if (props.variant === 'modal') {
    dismissLanGateModal();
  }
  void router.replace(redirect.value);
}

onMounted(() => {
  void load();
});

defineExpose({ load });
</script>

<style scoped src="./LanGatePanel.css"></style>
