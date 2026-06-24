<template>
  <div v-if="visible" class="mm-overlay" @click.self="close">
    <section class="mm-panel" role="dialog" aria-label="会议纪要">
      <header class="mm-head">
        <div class="mm-title"><i class="fa fa-file-lines" /> 会议纪要</div>
        <button class="mm-close" type="button" title="关闭" @click="close">
          <i class="fa fa-xmark" />
        </button>
      </header>

      <!-- 录入区：录音 + 粘贴 -->
      <div class="mm-input">
        <div class="mm-record-row">
          <button
            class="mm-rec-btn"
            :class="{ 'is-recording': recording }"
            type="button"
            :disabled="busy"
            @click="recording ? stopRecording() : startRecording()"
          >
            <i :class="recording ? 'fa fa-stop' : 'fa fa-microphone'" />
            {{ recording ? `停止录音 ${elapsed.toFixed(0)}s` : '开始录音' }}
          </button>
          <span v-if="transcribing" class="mm-hint"><i class="fa fa-spinner fa-pulse" /> 转写中…</span>
          <span v-else-if="recError" class="mm-hint mm-err">{{ recError }}</span>
          <span v-else class="mm-hint">录音停止后自动转写并追加到下方原文</span>
        </div>
        <textarea
          v-model="transcript"
          class="mm-transcript"
          rows="5"
          placeholder="会议转写原文（可直接粘贴，或用上方录音自动填入）"
        />
        <div class="mm-actions">
          <button
            class="mm-gen-btn"
            type="button"
            :disabled="!canGenerate"
            @click="generate"
          >
            <i v-if="generating" class="fa fa-spinner fa-pulse" />
            <i v-else class="fa fa-wand-magic-sparkles" />
            {{ generating ? '生成中…' : '一键生成三级纪要' }}
          </button>
          <span v-if="statusText" class="mm-status" :class="statusClass">{{ statusText }}</span>
        </div>
      </div>

      <!-- 三级 Tab -->
      <nav class="mm-tabs">
        <button
          v-for="lvl in levels"
          :key="lvl.id"
          class="mm-tab"
          :class="{ active: activeLevel === lvl.id }"
          type="button"
          @click="activeLevel = lvl.id"
        >
          {{ lvl.short || lvl.label }}
        </button>
      </nav>

      <div class="mm-content">
        <MessageBody v-if="activeContent" :content="activeContent" />
        <div v-else class="mm-empty">
          {{ result ? '该层暂无内容' : '生成后这里会显示：剧本式实录 → 架构图式总结 → 说人话' }}
        </div>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import MessageBody from '@/components/chat/MessageBody.vue';
import {
  meetingMinutesApi,
  type MeetingLevelDef,
  type MeetingMinute,
} from '@/api/meetingMinutes';

const FALLBACK_LEVELS: MeetingLevelDef[] = [
  { id: 'level1_script', label: '剧本式实录', short: '剧本', derives_from: 'raw' },
  { id: 'level2_architecture', label: '架构图式总结', short: '架构图', derives_from: 'level1_script' },
  { id: 'level3_plain', label: '说人话', short: '说人话', derives_from: 'level2_architecture' },
];

const visible = ref(false);
const transcript = ref('');
const levels = ref<MeetingLevelDef[]>(FALLBACK_LEVELS);
const activeLevel = ref<string>('level1_script');
const result = ref<MeetingMinute | null>(null);

const generating = ref(false);
const transcribing = ref(false);
const recording = ref(false);
const elapsed = ref(0);
const recError = ref('');

const busy = computed(() => generating.value || transcribing.value);
const canGenerate = computed(() => !busy.value && transcript.value.trim().length > 0);

const statusText = computed(() => {
  const s = result.value?.status;
  if (s === 'degraded') return '⚠️ AI 暂不可用，已保存原文，稍后可重试生成';
  if (s === 'failed') return `生成失败：${result.value?.error_message || '未知错误'}`;
  if (s === 'completed') return '✅ 已生成三级纪要';
  return '';
});
const statusClass = computed(() => ({
  'is-ok': result.value?.status === 'completed',
  'is-warn': result.value?.status === 'degraded',
  'is-err': result.value?.status === 'failed',
}));

const activeContent = computed(() => {
  const r = result.value;
  if (!r) return '';
  if (activeLevel.value === 'level1_script') return r.level1_script || '';
  if (activeLevel.value === 'level2_architecture') return r.level2_architecture || '';
  if (activeLevel.value === 'level3_plain') return r.level3_plain || '';
  return '';
});

// ── 录音（MediaRecorder） ──────────────────────────────────────────────
const PREFERRED_MIME = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg', 'audio/mp4', 'audio/wav'];
let recorder: MediaRecorder | null = null;
let stream: MediaStream | null = null;
let chunks: Blob[] = [];
let mimeType = '';
let startedAt = 0;
let tick: number | null = null;

function pickMime(): string {
  const MR = (window as unknown as { MediaRecorder?: typeof MediaRecorder }).MediaRecorder;
  if (!MR || typeof MR.isTypeSupported !== 'function') return '';
  for (const mt of PREFERRED_MIME) {
    try {
      if (MR.isTypeSupported(mt)) return mt;
    } catch {
      /* older browser */
    }
  }
  return '';
}

function releaseStream() {
  if (stream) {
    try {
      stream.getTracks().forEach((t) => t.stop());
    } catch {
      /* ignore */
    }
    stream = null;
  }
  recorder = null;
  if (tick) {
    window.clearInterval(tick);
    tick = null;
  }
}

async function startRecording() {
  recError.value = '';
  if (!navigator.mediaDevices?.getUserMedia) {
    recError.value = '当前浏览器不支持麦克风采集';
    return;
  }
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch (err) {
    const name = (err as { name?: string })?.name || '';
    recError.value =
      name === 'NotAllowedError' ? '麦克风权限被拒绝，请在地址栏授权' : '无法获取麦克风';
    return;
  }
  mimeType = pickMime();
  chunks = [];
  try {
    recorder = mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream);
  } catch {
    recError.value = '无法创建录音器';
    releaseStream();
    return;
  }
  recorder.addEventListener('dataavailable', (e: BlobEvent) => {
    if (e.data && e.data.size > 0) chunks.push(e.data);
  });
  recorder.addEventListener('stop', () => {
    const blob = new Blob(chunks, { type: mimeType || 'audio/webm' });
    chunks = [];
    releaseStream();
    recording.value = false;
    if (blob.size > 0) void transcribeBlob(blob);
  });
  recorder.start();
  startedAt = Date.now();
  recording.value = true;
  elapsed.value = 0;
  tick = window.setInterval(() => {
    elapsed.value = (Date.now() - startedAt) / 1000;
  }, 200);
}

function stopRecording() {
  if (recorder && recorder.state !== 'inactive') {
    try {
      recorder.stop();
    } catch {
      /* ignore */
    }
  }
}

async function transcribeBlob(blob: Blob) {
  transcribing.value = true;
  try {
    const text = await meetingMinutesApi.transcribe(blob, mimeType);
    if (text) {
      transcript.value = transcript.value.trim()
        ? `${transcript.value.trimEnd()}\n${text}`
        : text;
    } else {
      recError.value = '未识别到内容';
    }
  } catch (err) {
    recError.value = err instanceof Error ? err.message.slice(0, 60) : '转写失败';
  } finally {
    transcribing.value = false;
  }
}

// ── 生成 ───────────────────────────────────────────────────────────────
async function generate() {
  if (!canGenerate.value) return;
  generating.value = true;
  try {
    result.value = await meetingMinutesApi.generateAll(transcript.value.trim());
    // 默认展示有内容的最高层（说人话 > 架构图 > 剧本）
    if (result.value?.level3_plain) activeLevel.value = 'level3_plain';
    else if (result.value?.level2_architecture) activeLevel.value = 'level2_architecture';
    else activeLevel.value = 'level1_script';
  } catch (err) {
    result.value = {
      id: 0,
      title: null,
      status: 'failed',
      source_hash: '',
      level1_script: null,
      level2_architecture: null,
      level3_plain: null,
      error_message: err instanceof Error ? err.message : '请求失败',
    };
  } finally {
    generating.value = false;
  }
}

// ── 开关 + 事件 ─────────────────────────────────────────────────────────
function open() {
  visible.value = true;
}
function close() {
  if (recording.value) stopRecording();
  visible.value = false;
}
function onOpenEvent() {
  open();
}

onMounted(async () => {
  window.addEventListener('xcagi:open-meeting-minutes', onOpenEvent);
  try {
    const cfg = await meetingMinutesApi.getLevels();
    if (cfg?.levels?.length) levels.value = cfg.levels;
  } catch {
    /* 用兜底三级定义 */
  }
});

onBeforeUnmount(() => {
  window.removeEventListener('xcagi:open-meeting-minutes', onOpenEvent);
  releaseStream();
});
</script>

<style scoped>
.mm-overlay {
  position: fixed;
  inset: 0;
  z-index: 1200;
  background: rgba(0, 0, 0, 0.45);
  display: flex;
  justify-content: flex-end;
}
.mm-panel {
  width: min(560px, 96vw);
  height: 100%;
  background: var(--color-bg, #1b1c1f);
  color: var(--color-text, #e8e8ea);
  display: flex;
  flex-direction: column;
  box-shadow: -8px 0 24px rgba(0, 0, 0, 0.3);
}
.mm-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 16px;
  border-bottom: 1px solid var(--color-border, #2c2d31);
}
.mm-title {
  font-weight: 600;
  font-size: 15px;
}
.mm-close {
  background: none;
  border: none;
  color: inherit;
  font-size: 18px;
  cursor: pointer;
  opacity: 0.7;
}
.mm-close:hover {
  opacity: 1;
}
.mm-input {
  padding: 12px 16px;
  border-bottom: 1px solid var(--color-border, #2c2d31);
}
.mm-record-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
  flex-wrap: wrap;
}
.mm-rec-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 12px;
  border-radius: 8px;
  border: 1px solid var(--color-border, #2c2d31);
  background: var(--color-bg-soft, #232427);
  color: inherit;
  cursor: pointer;
}
.mm-rec-btn.is-recording {
  background: #c0392b;
  border-color: #c0392b;
  color: #fff;
}
.mm-rec-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.mm-hint {
  font-size: 12px;
  opacity: 0.7;
}
.mm-hint.mm-err,
.mm-err {
  color: #e06c5a;
  opacity: 1;
}
.mm-transcript {
  width: 100%;
  box-sizing: border-box;
  resize: vertical;
  border-radius: 8px;
  border: 1px solid var(--color-border, #2c2d31);
  background: var(--color-bg-soft, #232427);
  color: inherit;
  padding: 8px 10px;
  font-size: 13px;
  line-height: 1.5;
}
.mm-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 10px;
}
.mm-gen-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  border-radius: 8px;
  border: none;
  background: var(--color-primary, #18a85f);
  color: #fff;
  font-weight: 600;
  cursor: pointer;
}
.mm-gen-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.mm-status {
  font-size: 12px;
}
.mm-status.is-ok {
  color: #18a85f;
}
.mm-status.is-warn {
  color: #d29922;
}
.mm-status.is-err {
  color: #e06c5a;
}
.mm-tabs {
  display: flex;
  gap: 4px;
  padding: 10px 16px 0;
}
.mm-tab {
  padding: 7px 14px;
  border: none;
  border-bottom: 2px solid transparent;
  background: none;
  color: inherit;
  opacity: 0.65;
  cursor: pointer;
  font-size: 13px;
}
.mm-tab.active {
  opacity: 1;
  border-bottom-color: var(--color-primary, #18a85f);
  font-weight: 600;
}
.mm-content {
  flex: 1;
  overflow-y: auto;
  padding: 14px 16px;
}
.mm-empty {
  opacity: 0.55;
  font-size: 13px;
  padding: 24px 4px;
  text-align: center;
}
</style>
