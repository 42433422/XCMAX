<template>
  <div class="page-view project-factory-view">
    <div class="page-content">
      <header class="pf-head">
        <h2>项目工厂</h2>
        <p class="muted">
          让工厂版 AI 员工对所选项目派工。仅平台管理端可见；需在服务端配置
          <code>XCMAX_FACTORY_CAPABILITY_TOKEN</code> 才会启用工厂能力，否则降为只读产品域。
        </p>
      </header>

      <div v-if="errorMsg" class="pf-alert" role="alert">{{ errorMsg }}</div>

      <section class="pf-pickers" aria-label="项目与员工选择">
        <label class="pf-field">
          <span>项目</span>
          <select v-model="workspaceId" :disabled="loading" aria-label="选择项目">
            <option v-for="w in workspaces" :key="w.id" :value="w.id">
              {{ w.label }}（{{ w.isolation }}）
            </option>
          </select>
        </label>
        <label class="pf-field">
          <span>工厂员工</span>
          <select v-model="employeeId" :disabled="loading" aria-label="选择工厂员工" @change="loadMessages">
            <option v-for="e in employees" :key="e.id" :value="e.id">{{ e.display_name }}</option>
          </select>
        </label>
        <button type="button" class="btn btn-secondary btn-sm" :disabled="loading" @click="refresh">
          {{ loading ? '刷新中…' : '刷新' }}
        </button>
      </section>

      <section class="pf-messages" aria-label="派工记录">
        <p v-if="!messages.length" class="muted">还没有派工记录。选好项目和员工，下面发条指令试试。</p>
        <article v-for="m in messages" :key="m.id" class="pf-msg" :class="`pf-msg--${m.role}`">
          <div class="pf-msg__meta muted">
            {{ roleLabel(m.role) }}
            <span v-if="m.task_status"> · {{ m.task_status }}</span>
          </div>
          <div class="pf-msg__body">{{ m.body }}</div>
        </article>
      </section>

      <section class="pf-composer" aria-label="派工指令">
        <textarea
          v-model="draft"
          class="pf-input"
          rows="3"
          :disabled="sending"
          placeholder="例如：修复登录页的空指针，跑测试后回写日志"
          @keydown.ctrl.enter="send"
          @keydown.meta.enter="send"
        ></textarea>
        <button
          type="button"
          class="btn btn-primary"
          :disabled="sending || !draft.trim() || !currentEmployee?.endpoint || !workspaceId"
          @click="send"
        >
          {{ sending ? '派工中…' : '派工（⌘/Ctrl+Enter）' }}
        </button>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import {
  fetchClaudeSuperEmployeeMessages,
  type ClaudeSuperEmployeeMessage,
} from '@/api/claudeSuperEmployee';
import { fetchCodexSuperEmployeeMessages } from '@/api/codexSuperEmployee';
import {
  dispatchFactoryTask,
  fetchFactoryEmployees,
  fetchFactoryWorkspaces,
  type FactoryEmployee,
  type FactoryWorkspace,
} from '@/api/factoryConsole';

const workspaces = ref<FactoryWorkspace[]>([]);
const employees = ref<FactoryEmployee[]>([]);
const messages = ref<ClaudeSuperEmployeeMessage[]>([]);
const workspaceId = ref('');
const employeeId = ref('');
const draft = ref('');
const loading = ref(false);
const sending = ref(false);
const errorMsg = ref('');

const currentEmployee = computed(
  () => employees.value.find((e) => e.id === employeeId.value) ?? null,
);

function roleLabel(role: string): string {
  if (role === 'user') return '我';
  if (role === 'assistant') return '员工';
  return '系统';
}

function errText(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

async function loadMessages(): Promise<void> {
  const tool = currentEmployee.value?.display_tool;
  if (!tool) {
    messages.value = [];
    return;
  }
  try {
    messages.value =
      tool === 'Codex'
        ? await fetchCodexSuperEmployeeMessages({ scope: 'admin' })
        : await fetchClaudeSuperEmployeeMessages({ scope: 'admin' });
  } catch (e) {
    errorMsg.value = errText(e);
  }
}

async function refresh(): Promise<void> {
  loading.value = true;
  errorMsg.value = '';
  try {
    const [ws, emps] = await Promise.all([fetchFactoryWorkspaces(), fetchFactoryEmployees()]);
    workspaces.value = ws;
    employees.value = emps;
    if (!workspaceId.value && ws.length) workspaceId.value = ws[0].id;
    if (!employeeId.value && emps.length) employeeId.value = emps[0].id;
    await loadMessages();
  } catch (e) {
    errorMsg.value = errText(e);
  } finally {
    loading.value = false;
  }
}

async function send(): Promise<void> {
  const text = draft.value.trim();
  const emp = currentEmployee.value;
  if (!text || !emp?.endpoint || !workspaceId.value) return;
  sending.value = true;
  errorMsg.value = '';
  try {
    await dispatchFactoryTask(emp.endpoint, text, workspaceId.value);
    draft.value = '';
    await loadMessages();
  } catch (e) {
    errorMsg.value = errText(e);
  } finally {
    sending.value = false;
  }
}

onMounted(refresh);
</script>

<style scoped>
.project-factory-view .pf-head {
  margin-bottom: 1rem;
}
.pf-head code {
  font-size: 0.85em;
  padding: 0.1em 0.35em;
  border-radius: 4px;
  background: var(--color-surface, #f0f0f0);
}
.pf-alert {
  padding: 0.6rem 0.8rem;
  border-radius: 8px;
  background: var(--color-danger-bg, #fff0f0);
  color: var(--color-danger, #b42318);
  margin-bottom: 0.8rem;
}
.pf-pickers {
  display: flex;
  gap: 1rem;
  align-items: flex-end;
  flex-wrap: wrap;
  margin-bottom: 1rem;
}
.pf-field {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  font-size: 0.85rem;
}
.pf-field select {
  min-width: 12rem;
  padding: 0.4rem;
}
.pf-messages {
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
  margin-bottom: 1rem;
  max-height: 50vh;
  overflow-y: auto;
}
.pf-msg {
  padding: 0.6rem 0.8rem;
  border-radius: 10px;
  background: var(--color-surface, #f6f6f6);
}
.pf-msg--user {
  background: var(--color-primary-soft, #eef4ff);
}
.pf-msg__meta {
  font-size: 0.75rem;
  margin-bottom: 0.2rem;
}
.pf-msg__body {
  white-space: pre-wrap;
  word-break: break-word;
}
.pf-composer {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}
.pf-input {
  width: 100%;
  padding: 0.6rem;
  border-radius: 8px;
  resize: vertical;
}
.muted {
  color: var(--color-text-muted, #888);
}
</style>
