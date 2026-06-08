<template>
  <teleport to="body">
    <div
      v-if="showOverlay"
      class="fhd-write-gate-root"
      role="dialog"
      aria-modal="true"
      aria-labelledby="fhd-global-write-title"
    >
      <div class="fhd-write-gate-backdrop" @click="onBackdropClick" />
      <div class="fhd-write-gate-panel" @click.stop>
        <h2 id="fhd-global-write-title" class="fhd-write-gate-title">
          二级数据库写入口令
        </h2>
        <p class="fhd-write-gate-desc">
          {{ reasonText }}
          该操作为<strong>写入类</strong>工具调用，需要
          <code>X-FHD-Db-Write-Token</code>（<code>FHD_DB_WRITE_TOKEN</code>，
          本机 <code>xcagi_db_write_token</code>）。口令可保存在本机，但每次发起写入类对话须在此确认后才会提交给 AI；确认后将自动续跑当前请求。
        </p>
        <label class="fhd-write-gate-label" for="fhd-global-write-input">二级密钥</label>
        <input
          id="fhd-global-write-input"
          ref="inputRef"
          v-model="password"
          type="password"
          class="fhd-write-gate-input"
          autocomplete="off"
          @keydown.enter.prevent="onSubmit"
        />
        <p v-if="errorText" class="fhd-write-gate-error">{{ errorText }}</p>
        <div class="fhd-write-gate-actions">
          <button
            type="button"
            class="fhd-write-gate-btn-secondary"
            :disabled="busy"
            @click="onCancel"
          >
            取消
          </button>
          <button
            type="button"
            class="fhd-write-gate-btn"
            :disabled="busy"
            @click="onSubmit"
          >
            {{ busy ? '保存中…' : '保存并继续' }}
          </button>
        </div>
      </div>
    </div>
  </teleport>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue';
import {
  FHD_DB_WRITE_UNLOCKED_EVENT,
  LS_DB_WRITE_TOKEN,
  XCAGI_PROMPT_DB_WRITE_TOKEN_EVENT,
  saveStoredWriteToken,
} from './dbTokenHeaders';

const visible = ref(false);
const password = ref('');
const errorText = ref('');
const busy = ref(false);
const reasonText = ref('检测到需要写入数据库的操作（例如 Excel 导入）。');
const inputRef = ref<HTMLInputElement | null>(null);

const showOverlay = computed(() => visible.value);

function dispatchUnlocked() {
  if (typeof window === 'undefined') return;
  window.dispatchEvent(new CustomEvent(FHD_DB_WRITE_UNLOCKED_EVENT));
}

function closePanel() {
  visible.value = false;
  password.value = '';
  errorText.value = '';
  busy.value = false;
}

function onSubmit() {
  errorText.value = '';
  const p = password.value.trim();
  if (!p) {
    errorText.value = '请输入二级写入口令。';
    return;
  }
  busy.value = true;
  try {
    saveStoredWriteToken(p);
    dispatchUnlocked();
    closePanel();
  } finally {
    busy.value = false;
  }
}

function onCancel() {
  closePanel();
}

function onBackdropClick() {
  closePanel();
}

function onPromptFromChat(evt: Event) {
  const detail = (evt as CustomEvent).detail || {};
  const hint = String(detail.description || detail.message || '').trim();
  reasonText.value = hint
    ? `AI 指出：${hint}。`
    : '检测到需要写入数据库的操作（例如 Excel 导入）。';
  errorText.value = '';
  visible.value = true;
  nextTick(() => {
    inputRef.value?.focus();
  });
}

function onStorage(e: StorageEvent) {
  if (e.key === LS_DB_WRITE_TOKEN) return;
}

function onKeyDown(e: KeyboardEvent) {
  if (!visible.value) return;
  if (e.key === 'Escape') {
    e.preventDefault();
    closePanel();
  }
}

onMounted(() => {
  window.addEventListener(XCAGI_PROMPT_DB_WRITE_TOKEN_EVENT, onPromptFromChat);
  window.addEventListener('storage', onStorage);
  window.addEventListener('keydown', onKeyDown);
});

onUnmounted(() => {
  window.removeEventListener(XCAGI_PROMPT_DB_WRITE_TOKEN_EVENT, onPromptFromChat);
  window.removeEventListener('storage', onStorage);
  window.removeEventListener('keydown', onKeyDown);
});
</script>

<style scoped>
.fhd-write-gate-root {
  position: fixed;
  inset: 0;
  z-index: 2147483646;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 16px;
  box-sizing: border-box;
}
.fhd-write-gate-backdrop {
  position: absolute;
  inset: 0;
  background: rgba(15, 23, 42, 0.55);
}
.fhd-write-gate-panel {
  position: relative;
  max-width: 440px;
  width: 100%;
  padding: 24px;
  border-radius: 12px;
  background: #fff;
  color: #0f172a;
  box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.35);
}
.fhd-write-gate-title {
  margin: 0 0 12px;
  font-size: 1.25rem;
  color: #b91c1c;
}
.fhd-write-gate-desc {
  margin: 0 0 16px;
  font-size: 0.9rem;
  line-height: 1.55;
  color: #475569;
}
.fhd-write-gate-label {
  display: block;
  font-size: 0.85rem;
  margin-bottom: 6px;
  font-weight: 600;
}
.fhd-write-gate-input {
  width: 100%;
  box-sizing: border-box;
  padding: 10px 12px;
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  font-size: 1rem;
}
.fhd-write-gate-error {
  margin: 10px 0 0;
  font-size: 0.85rem;
  color: #b91c1c;
}
.fhd-write-gate-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 18px;
}
.fhd-write-gate-btn {
  padding: 10px 20px;
  border: none;
  border-radius: 8px;
  background: #b91c1c;
  color: #fff;
  font-size: 0.95rem;
  cursor: pointer;
}
.fhd-write-gate-btn:disabled {
  opacity: 0.65;
  cursor: not-allowed;
}
.fhd-write-gate-btn-secondary {
  padding: 10px 20px;
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  background: #f8fafc;
  color: #334155;
  font-size: 0.95rem;
  cursor: pointer;
}
.fhd-write-gate-btn-secondary:disabled {
  opacity: 0.65;
  cursor: not-allowed;
}
</style>
