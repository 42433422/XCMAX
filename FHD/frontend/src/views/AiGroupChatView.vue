<template>
  <div class="aigc">
    <!-- 左：群列表 -->
    <aside class="aigc-list">
      <div class="aigc-list__head">
        <span>群聊</span>
        <button class="aigc-icon-btn" title="创建群聊" @click="onCreateGroup">＋</button>
      </div>
      <div class="aigc-list__body">
        <button
          v-for="g in groups"
          :key="g.id"
          class="aigc-group"
          :class="{ 'is-active': activeGroup && activeGroup.id === g.id }"
          @click="selectGroup(g)"
        >
          <div class="aigc-group__avatar">群</div>
          <div class="aigc-group__main">
            <div class="aigc-group__name">{{ g.name }}</div>
            <div class="aigc-group__sub">
              {{ g.last_message_preview || (g.member_count ? `${g.member_count} 个 AI 成员` : '还没有成员，进群把 AI 拉进来') }}
            </div>
          </div>
        </button>
        <div v-if="groupsLoading && !groups.length" class="aigc-empty">加载中…</div>
        <div v-else-if="groupsError && !groups.length" class="aigc-empty">
          加载失败
          <button class="aigc-text-btn aigc-retry" @click="loadGroups">重试</button>
        </div>
      </div>
    </aside>

    <!-- 右：会话 -->
    <section class="aigc-chat" v-if="activeGroup">
      <header class="aigc-chat__head">
        <div>
          <div class="aigc-chat__title">{{ activeGroup.name }}</div>
          <div class="aigc-chat__sub" v-if="activeGroup.member_count">{{ activeGroup.member_count }} 个 AI 成员</div>
        </div>
        <button class="aigc-text-btn" @click="showMembers = !showMembers">群成员</button>
      </header>

      <div class="aigc-chat__body" ref="bodyRef">
        <div v-for="m in messages" :key="m.id" class="aigc-msg" :class="{ 'is-user': m.role === 'user' }">
          <div v-if="m.role !== 'user'" class="aigc-msg__avatar">{{ (m.sender_name || 'AI').slice(0, 1) }}</div>
          <div class="aigc-msg__col">
            <div v-if="m.role !== 'user'" class="aigc-msg__sender">{{ m.sender_name }}</div>
            <div class="aigc-msg__bubble">{{ m.body }}</div>
          </div>
        </div>
        <div v-if="sending" class="aigc-typing">AI 成员正在回复…</div>
        <div v-if="!messages.length && !sending" class="aigc-empty">
          {{ activeGroup.member_count ? '群里安静得很，发条消息试试' : '点「群成员」把 AI 员工拉进群，然后开聊' }}
        </div>
      </div>

      <footer class="aigc-chat__input">
        <input
          v-model="input"
          class="aigc-input"
          placeholder="发群消息（@成员 可单独点名）"
          :disabled="sending"
          @keyup.enter="send"
        />
        <button class="aigc-send" :disabled="!input.trim() || sending" @click="send">
          {{ sending ? '发送中…' : '发送' }}
        </button>
      </footer>
    </section>
    <section class="aigc-chat aigc-chat--empty" v-else>
      <div class="aigc-empty">选择左侧的群开始聊天</div>
    </section>

    <!-- 群成员抽屉 -->
    <aside class="aigc-members" v-if="showMembers && activeGroup">
      <div class="aigc-members__head">群成员（{{ activeGroup.member_count }}）</div>
      <div v-for="mem in activeGroup.members" :key="mem.employee_id" class="aigc-member">
        <span class="aigc-member__name">{{ mem.name }}</span>
        <button class="aigc-text-btn aigc-text-btn--danger" @click="removeMember(mem.employee_id)">移出</button>
      </div>
      <div class="aigc-members__head">添加 AI 成员</div>
      <div v-if="!addableEmployees.length" class="aigc-empty aigc-empty--sm">没有可添加的 AI 员工</div>
      <button v-for="e in addableEmployees" :key="e.employee_id" class="aigc-member aigc-member--add" @click="addMember(e)">
        <span class="aigc-member__name">{{ e.name }}</span>
        <span class="aigc-member__add">＋</span>
      </button>
    </aside>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue';
import {
  addAiGroupMember,
  createAiGroup,
  fetchAiGroupMessages,
  fetchAiGroups,
  postAiGroupMessage,
  removeAiGroupMember,
  type AiGroup,
  type AiGroupMember,
  type AiGroupMessage,
} from '@/api/aiGroups';
import { apiFetch } from '@/utils/apiBase';
import { showAppToast } from '@/composables/useAppToast';

type PickEmployee = { employee_id: string; mod_id: string; name: string; avatar: string; summary: string };

const groups = ref<AiGroup[]>([]);
const groupsLoading = ref(true);
const groupsError = ref<Error | null>(null);
const activeGroup = ref<AiGroup | null>(null);
const messages = ref<AiGroupMessage[]>([]);
const employees = ref<PickEmployee[]>([]);
const input = ref('');
const sending = ref(false);
const showMembers = ref(false);
const bodyRef = ref<HTMLElement | null>(null);

const addableEmployees = computed(() => {
  const inGroup = new Set((activeGroup.value?.members || []).map((m: AiGroupMember) => m.employee_id));
  return employees.value.filter((e) => !inGroup.has(e.employee_id));
});

async function loadGroups(): Promise<void> {
  groupsLoading.value = true;
  groupsError.value = null;
  try {
    groups.value = await fetchAiGroups('admin');
    if (!activeGroup.value && groups.value.length) await selectGroup(groups.value[0]);
  } catch (error) {
    groupsError.value = error instanceof Error ? error : new Error('加载失败');
  } finally {
    groupsLoading.value = false;
  }
}

async function selectGroup(g: AiGroup): Promise<void> {
  activeGroup.value = g;
  messages.value = [];
  try {
    messages.value = await fetchAiGroupMessages(g.id, 'admin');
    await scrollToBottom();
  } catch {
    /* ignore */
  }
}

async function send(): Promise<void> {
  const text = input.value.trim();
  const g = activeGroup.value;
  if (!text || !g || sending.value) return;
  input.value = '';
  messages.value = [
    ...messages.value,
    { id: `local-${messages.value.length}`, group_id: g.id, role: 'user', sender_id: 'user', sender_name: '我', sender_avatar: '', body: text, created_at: '' },
  ];
  sending.value = true;
  await scrollToBottom();
  try {
    const res = await postAiGroupMessage(g.id, text, [], 'admin');
    messages.value = [...messages.value.filter((m) => !m.id.startsWith('local-')), ...res.messages];
    if (res.group) {
      activeGroup.value = res.group;
      groups.value = groups.value.map((x) => (x.id === res.group!.id ? res.group! : x));
    }
  } catch (error) {
    showAppToast(error instanceof Error ? error.message : '发送失败，请重试', 'error');
  } finally {
    sending.value = false;
    await scrollToBottom();
  }
}

async function onCreateGroup(): Promise<void> {
  const name = window.prompt('群名称');
  if (!name || !name.trim()) return;
  try {
    await createAiGroup(name.trim(), 'admin');
    await loadGroups();
  } catch {
    /* ignore */
  }
}

async function addMember(e: PickEmployee): Promise<void> {
  const g = activeGroup.value;
  if (!g) return;
  try {
    const updated = await addAiGroupMember(g.id, e, 'admin');
    if (updated) {
      activeGroup.value = updated;
      groups.value = groups.value.map((x) => (x.id === updated.id ? updated : x));
    }
  } catch (error) {
    showAppToast(error instanceof Error ? error.message : '添加成员失败，请重试', 'error');
  }
}

async function removeMember(employeeId: string): Promise<void> {
  const g = activeGroup.value;
  if (!g) return;
  if (!window.confirm('确定要将此成员移出群吗？')) return;
  try {
    const updated = await removeAiGroupMember(g.id, employeeId, 'admin');
    if (updated) {
      activeGroup.value = updated;
      groups.value = groups.value.map((x) => (x.id === updated.id ? updated : x));
    }
  } catch (error) {
    showAppToast(error instanceof Error ? error.message : '移出成员失败，请重试', 'error');
  }
}

async function loadEmployees(): Promise<void> {
  try {
    const res = await apiFetch('/api/mobile/v1/admin/employees', { headers: { 'Content-Type': 'application/json' } });
    const json = (await res.json()) as { data?: { items?: unknown[]; employees?: unknown[] }; items?: unknown[]; employees?: unknown[] };
    const payload = json.data || json;
    const rows = (payload.items || payload.employees || []) as Array<Record<string, unknown>>;
    employees.value = rows
      .map((r) => ({
        employee_id: String(r.id || r.employee_id || '').trim(),
        mod_id: String(r.mod_id || '').trim(),
        name: String(r.display_name || r.name || r.id || '').trim(),
        avatar: String(r.avatar || r.avatar_url || '').trim(),
        summary: String(r.description || r.summary || '').trim(),
      }))
      .filter((e) => e.employee_id);
  } catch {
    employees.value = [];
  }
}

async function scrollToBottom(): Promise<void> {
  await nextTick();
  const el = bodyRef.value;
  if (el) el.scrollTop = el.scrollHeight;
}

onMounted(() => {
  loadGroups();
  loadEmployees();
});
</script>

<style scoped>
.aigc { display: flex; height: 100%; min-height: 0; background: var(--color-bg, #f5f6f7); }
.aigc-list { width: 280px; border-right: 1px solid var(--color-border, #e5e7eb); background: var(--color-surface, #fff); display: flex; flex-direction: column; }
.aigc-list__head { display: flex; align-items: center; justify-content: space-between; padding: 14px 16px; font-weight: 600; border-bottom: 1px solid var(--color-border, #e5e7eb); }
.aigc-list__body { overflow-y: auto; flex: 1; }
.aigc-group { display: flex; gap: 10px; align-items: center; width: 100%; padding: 12px 16px; border: none; background: none; cursor: pointer; text-align: left; border-bottom: 1px solid var(--color-border-weak, #f0f0f0); }
.aigc-group.is-active { background: var(--color-primary-soft, #eef4ff); }
.aigc-group__avatar { width: 40px; height: 40px; border-radius: 9px; background: #3370ff22; color: #3370ff; display: flex; align-items: center; justify-content: center; font-size: 14px; flex: none; }
.aigc-group__main { min-width: 0; }
.aigc-group__name { font-size: 14px; font-weight: 500; }
.aigc-group__sub { font-size: 12px; color: var(--color-text-2, #888); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.aigc-chat { flex: 1; display: flex; flex-direction: column; min-width: 0; }
.aigc-chat--empty { align-items: center; justify-content: center; }
.aigc-chat__head { display: flex; align-items: center; justify-content: space-between; padding: 12px 18px; border-bottom: 1px solid var(--color-border, #e5e7eb); background: var(--color-surface, #fff); }
.aigc-chat__title { font-weight: 600; }
.aigc-chat__sub { font-size: 12px; color: var(--color-text-2, #888); }
.aigc-chat__body { flex: 1; overflow-y: auto; padding: 16px 20px; display: flex; flex-direction: column; gap: 12px; }
.aigc-msg { display: flex; gap: 8px; align-items: flex-start; max-width: 72%; }
.aigc-msg.is-user { align-self: flex-end; flex-direction: row-reverse; }
.aigc-msg__avatar { width: 34px; height: 34px; border-radius: 8px; background: #5b8def22; color: #3a5bb8; display: flex; align-items: center; justify-content: center; font-size: 13px; flex: none; }
.aigc-msg__col { display: flex; flex-direction: column; }
.aigc-msg__sender { font-size: 11px; color: var(--color-text-2, #999); margin: 0 2px 3px; }
.aigc-msg__bubble { padding: 9px 12px; border-radius: 10px; background: var(--color-surface, #fff); border: 1px solid var(--color-border-weak, #eee); font-size: 14px; line-height: 1.5; white-space: pre-wrap; word-break: break-word; }
.aigc-msg.is-user .aigc-msg__bubble { background: #95ec69; border-color: #7fd957; color: #1f2329; }
.aigc-typing { font-size: 12px; color: var(--color-text-2, #999); }
.aigc-chat__input { display: flex; gap: 10px; padding: 12px 16px; border-top: 1px solid var(--color-border, #e5e7eb); background: var(--color-surface, #fff); }
.aigc-input { flex: 1; border: 1px solid var(--color-border, #ddd); border-radius: 8px; padding: 9px 12px; font-size: 14px; outline: none; }
.aigc-send { padding: 0 18px; border: none; border-radius: 8px; background: #07c160; color: #fff; cursor: pointer; }
.aigc-send:disabled { background: #c8c9cc; cursor: not-allowed; }
.aigc-members { width: 240px; border-left: 1px solid var(--color-border, #e5e7eb); background: var(--color-surface, #fff); padding: 12px 14px; overflow-y: auto; }
.aigc-members__head { font-size: 12px; color: var(--color-text-2, #888); margin: 12px 0 6px; }
.aigc-member { display: flex; align-items: center; justify-content: space-between; width: 100%; padding: 8px 4px; border: none; background: none; border-bottom: 1px solid var(--color-border-weak, #f0f0f0); cursor: default; }
.aigc-member--add { cursor: pointer; }
.aigc-member__name { font-size: 13px; }
.aigc-member__add { color: #3370ff; }
.aigc-icon-btn { border: none; background: none; font-size: 18px; cursor: pointer; color: var(--color-text-2, #666); }
.aigc-text-btn { border: 1px solid var(--color-border, #ddd); background: none; border-radius: 6px; padding: 4px 10px; font-size: 12px; cursor: pointer; }
.aigc-text-btn--danger { color: #e34d59; border-color: #f0c2c5; }
.aigc-empty { color: var(--color-text-2, #999); font-size: 13px; padding: 20px; text-align: center; }
.aigc-empty--sm { padding: 8px; text-align: left; }
.aigc-retry { margin-left: 8px; }
</style>
