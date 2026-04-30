<template>
  <teleport to="body">
    <div
      v-if="showOverlay"
      class="fhd-read-gate-root"
      role="dialog"
      aria-modal="true"
      aria-labelledby="fhd-global-read-title"
    >
      <div class="fhd-read-gate-backdrop" @click="fabOpen = false" />
      <div class="fhd-read-gate-panel" @click.stop>
        <h2 id="fhd-global-read-title" class="fhd-read-gate-title">一级数据库口令（只读受保护接口）</h2>
        <p class="fhd-read-gate-desc">
          产品列表、价表/销售合同 Word 预览等受保护 GET，以及<strong>销售合同话术解析</strong>（<code>POST …/resolve-from-text</code>）需要 <code>X-FHD-Db-Read-Token</code>（与 <code>FHD_DB_READ_TOKEN</code> 等一致）。输入一次会写入本机 <code>xcagi_db_read_token</code>，并与「产品管理」页 5 分钟内免重复输入共用；<strong>新增/修改/删除产品</strong>另需二级
          <code>X-FHD-Db-Write-Token</code>（<code>FHD_DB_WRITE_TOKEN</code>，localStorage <code>xcagi_db_write_token</code>）。
        </p>
        <label class="fhd-read-gate-label" for="fhd-global-read-input">口令</label>
        <input
          id="fhd-global-read-input"
          v-model="password"
          type="password"
          class="fhd-read-gate-input"
          autocomplete="off"
          @keydown.enter.prevent="onUnlock"
        />
        <p v-if="errorText" class="fhd-read-gate-error">{{ errorText }}</p>
        <div class="fhd-read-gate-actions">
          <button type="button" class="fhd-read-gate-btn" :disabled="busy" @click="onUnlock">
            {{ busy ? '验证中…' : '保存并继续' }}
          </button>
        </div>
      </div>
    </div>
    <button
      v-else-if="showFab"
      type="button"
      class="fhd-read-fab"
      title="输入一级数据库口令"
      @click="onFabClick"
    >
      一级锁
    </button>
  </teleport>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue';
import {
  FHD_DB_READ_UNLOCKED_EVENT,
  LS_DB_READ_TOKEN,
  XCAGI_PROMPT_DB_READ_TOKEN_EVENT,
  getProductsReadLockState,
  probeProductsReadAccess,
  saveStoredReadToken,
  touchProductsReadGateGrace,
} from './dbTokenHeaders';

const props = defineProps<{ apiBase?: string }>();

const booting = ref(true);
const blocked = ref(false);
const fabOpen = ref(false);
const password = ref('');
const errorText = ref('');
const busy = ref(false);

const showOverlay = computed(() => !booting.value && blocked.value && fabOpen.value);
const showFab = computed(() => !booting.value && blocked.value && !fabOpen.value);

function dispatchUnlocked() {
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent(FHD_DB_READ_UNLOCKED_EVENT));
  }
}

async function evaluate() {
  errorText.value = '';
  const state = await getProductsReadLockState(props.apiBase || '');
  booting.value = false;
  if (state === 'open') {
    blocked.value = false;
    fabOpen.value = false;
    touchProductsReadGateGrace();
    dispatchUnlocked();
    return;
  }
  blocked.value = true;
  fabOpen.value = true;
  if (state === 'locked_bad_token') {
    errorText.value = '本地保存的口令无效，请重新输入。';
  }
}

function onFabClick() {
  fabOpen.value = true;
  errorText.value = '';
}

async function onUnlock() {
  errorText.value = '';
  const p = password.value.trim();
  if (!p) {
    errorText.value = '请输入口令。';
    return;
  }
  busy.value = true;
  try {
    saveStoredReadToken(p);
    const ok = await probeProductsReadAccess(props.apiBase || '', {
      allowStoredTokenBypassGrace: true,
    });
    if (!ok) {
      errorText.value = '口令错误或服务不可达，请重试。';
      return;
    }
    blocked.value = false;
    fabOpen.value = false;
    password.value = '';
    touchProductsReadGateGrace();
    dispatchUnlocked();
  } finally {
    busy.value = false;
  }
}

function onStorage(e: StorageEvent) {
  if (e.key === null || e.key === LS_DB_READ_TOKEN) {
    void evaluate();
  }
}

/** 受保护接口 403（如销售合同话术解析）时由 api/core 派发，避免只报错不弹窗。 */
function onPromptFromApi() {
  booting.value = false;
  blocked.value = true;
  fabOpen.value = true;
  if (!errorText.value) {
    errorText.value = '该操作需要一级只读口令（与产品列表同源）。请输入后点「保存并继续」。';
  }
}

onMounted(() => {
  void evaluate();
  window.addEventListener('storage', onStorage);
  window.addEventListener(XCAGI_PROMPT_DB_READ_TOKEN_EVENT, onPromptFromApi);
});

onUnmounted(() => {
  window.removeEventListener('storage', onStorage);
  window.removeEventListener(XCAGI_PROMPT_DB_READ_TOKEN_EVENT, onPromptFromApi);
});

watch(
  () => props.apiBase,
  () => {
    booting.value = true;
    void evaluate();
  },
);
</script>

<style scoped>
.fhd-read-gate-root {
  position: fixed;
  inset: 0;
  z-index: 2147483645;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 16px;
  box-sizing: border-box;
}
.fhd-read-gate-backdrop {
  position: absolute;
  inset: 0;
  background: rgba(15, 23, 42, 0.55);
}
.fhd-read-gate-panel {
  position: relative;
  max-width: 420px;
  width: 100%;
  padding: 24px;
  border-radius: 12px;
  background: #fff;
  color: #0f172a;
  box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.35);
}
.fhd-read-gate-title {
  margin: 0 0 12px;
  font-size: 1.25rem;
}
.fhd-read-gate-desc {
  margin: 0 0 16px;
  font-size: 0.9rem;
  line-height: 1.5;
  color: #475569;
}
.fhd-read-gate-label {
  display: block;
  font-size: 0.85rem;
  margin-bottom: 6px;
  font-weight: 600;
}
.fhd-read-gate-input {
  width: 100%;
  box-sizing: border-box;
  padding: 10px 12px;
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  font-size: 1rem;
}
.fhd-read-gate-error {
  margin: 10px 0 0;
  font-size: 0.85rem;
  color: #b91c1c;
}
.fhd-read-gate-actions {
  margin-top: 18px;
}
.fhd-read-gate-btn {
  padding: 10px 20px;
  border: none;
  border-radius: 8px;
  background: #2563eb;
  color: #fff;
  font-size: 0.95rem;
  cursor: pointer;
}
.fhd-read-gate-btn:disabled {
  opacity: 0.65;
  cursor: not-allowed;
}
.fhd-read-fab {
  position: fixed;
  right: 16px;
  bottom: 16px;
  z-index: 2147483640;
  padding: 10px 14px;
  border: none;
  border-radius: 999px;
  background: #1e293b;
  color: #f8fafc;
  font-size: 0.85rem;
  cursor: pointer;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.25);
}
</style>
