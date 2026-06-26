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
        <div v-if="!groups.length" class="aigc-empty">加载中…</div>
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
        <div
          v-for="m in messages"
          :key="m.id"
          class="aigc-msg"
          :class="{
            'is-user': m.role === 'user',
            [messageUi(m).bubbleClass]: Boolean(messageUi(m).bubbleClass),
          }"
        >
          <div v-if="m.role !== 'user'" class="aigc-msg__avatar">
            <img
              v-if="messageAvatarSrc(m)"
              class="aigc-msg__avatar-img"
              :src="messageAvatarSrc(m) || undefined"
              alt=""
              decoding="async"
              draggable="false"
            />
            <template v-else>{{ (m.sender_name || 'AI').slice(0, 1) }}</template>
          </div>
          <div class="aigc-msg__col">
            <div v-if="m.role !== 'user'" class="aigc-msg__sender">{{ m.sender_name }}</div>
            <div
              v-if="messageUi(m).badge"
              class="aigc-msg__badge"
              :class="{ 'is-review': messageUi(m).needsReview }"
            >
              {{ messageUi(m).badge }}
            </div>
            <div class="aigc-msg__bubble">{{ m.body }}</div>
          </div>
        </div>
        <div v-if="sending" class="aigc-typing">{{ sendingLabel }}</div>
        <div v-if="!messages.length && !sending" class="aigc-empty">
          {{ activeGroup.member_count ? '群里安静得很，发条消息试试' : '点「群成员」把 AI 员工拉进群，然后开聊' }}
        </div>
      </div>

      <footer class="aigc-chat__input">
        <input
          v-model="input"
          class="aigc-input"
          :placeholder="inputPlaceholder"
          :disabled="sending"
          @keyup.enter="send"
        />
        <button
          type="button"
          class="aigc-mode"
          :class="{ 'is-active': dispatchMode }"
          :disabled="sending"
          @click="dispatchMode = !dispatchMode"
        >
          派工
        </button>
        <button class="aigc-send" :disabled="!input.trim() || sending" @click="send">发送</button>
      </footer>
    </section>
    <section class="aigc-chat aigc-chat--empty" v-else>
      <div class="aigc-empty">选择左侧的群开始聊天</div>
    </section>

    <!-- 群成员抽屉 -->
    <aside class="aigc-members" v-if="showMembers && activeGroup">
      <div class="aigc-members__head">群成员（{{ activeGroup.member_count }}）</div>
      <div v-for="mem in activeGroup.members" :key="mem.employee_id" class="aigc-member">
        <div class="aigc-member__main">
          <div class="aigc-member__avatar">
            <img
              v-if="memberAvatarSrc(mem)"
              class="aigc-member__avatar-img"
              :src="memberAvatarSrc(mem) || undefined"
              alt=""
              decoding="async"
              draggable="false"
            />
            <template v-else>{{ (mem.name || 'AI').slice(0, 1) }}</template>
          </div>
          <span class="aigc-member__name">{{ mem.name }}</span>
        </div>
        <button class="aigc-text-btn aigc-text-btn--danger" @click="removeMember(mem.employee_id)">移出</button>
      </div>
      <div class="aigc-members__head">添加 AI 成员</div>
      <div v-if="!addableEmployees.length" class="aigc-empty aigc-empty--sm">没有可添加的 AI 员工</div>
      <button v-for="e in addableEmployees" :key="e.employee_id" class="aigc-member aigc-member--add" @click="addMember(e)">
        <div class="aigc-member__main">
          <div class="aigc-member__avatar">
            <img
              v-if="pickEmployeeAvatarSrc(e)"
              class="aigc-member__avatar-img"
              :src="pickEmployeeAvatarSrc(e) || undefined"
              alt=""
              decoding="async"
              draggable="false"
            />
            <template v-else>{{ (e.name || 'AI').slice(0, 1) }}</template>
          </div>
          <span class="aigc-member__name">{{ e.name }}</span>
        </div>
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
import { resolveSuperEmployeeAvatarSrc } from '@/constants/superEmployeeAvatars';
import { apiFetch } from '@/utils/apiBase';
import { groupSendingLabel, resolveAiGroupMessageUi } from '@/utils/aiGroupMessageUi';

type PickEmployee = { employee_id: string; mod_id: string; name: string; avatar: string; summary: string };

const groups = ref<AiGroup[]>([]);
const activeGroup = ref<AiGroup | null>(null);
const messages = ref<AiGroupMessage[]>([]);
const employees = ref<PickEmployee[]>([]);
const input = ref('');
const sending = ref(false);
const showMembers = ref(false);
const dispatchMode = ref(false);
const bodyRef = ref<HTMLElement | null>(null);

const addableEmployees = computed(() => {
  const inGroup = new Set((activeGroup.value?.members || []).map((m: AiGroupMember) => m.employee_id));
  return employees.value.filter((e) => !inGroup.has(e.employee_id));
});

const inputPlaceholder = computed(() =>
  dispatchMode.value ? '派工给群成员（@成员 可点对点派工）' : '发群消息（@成员 可单独点名）',
);

const sendingLabel = computed(() => groupSendingLabel(dispatchMode.value));

function messageUi(m: AiGroupMessage) {
  return resolveAiGroupMessageUi(m.kind, m.status, m.body);
}

function withBaseUrl(path: string): string {
  const raw = String(path || '').trim();
  if (!raw) return '';
  if (/^https?:\/\//i.test(raw)) return raw;
  const base = String(import.meta.env.BASE_URL || '/');
  return `${base.replace(/\/$/, '')}/${raw.replace(/^\//, '')}`;
}

function memberAvatarSrc(member: AiGroupMember): string | null {
  const resolved = resolveSuperEmployeeAvatarSrc(member.employee_id, member.avatar);
  return resolved ? withBaseUrl(resolved) : null;
}

function pickEmployeeAvatarSrc(employee: PickEmployee): string | null {
  const resolved = resolveSuperEmployeeAvatarSrc(employee.employee_id, employee.avatar);
  return resolved ? withBaseUrl(resolved) : null;
}

function messageAvatarSrc(message: AiGroupMessage): string | null {
  const resolved = resolveSuperEmployeeAvatarSrc(message.sender_id, message.sender_avatar);
  return resolved ? withBaseUrl(resolved) : null;
}

async function loadGroups(): Promise<void> {
  try {
    groups.value = await fetchAiGroups('admin');
    if (!activeGroup.value && groups.value.length) await selectGroup(groups.value[0]);
  } catch {
    /* 静默：保留旧值 */
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
    const res = await postAiGroupMessage(g.id, text, [], 'admin', { dispatch: dispatchMode.value });
    messages.value = [...messages.value.filter((m) => !m.id.startsWith('local-')), ...res.messages];
    if (res.group) {
      activeGroup.value = res.group;
      groups.value = groups.value.map((x) => (x.id === res.group!.id ? res.group! : x));
    }
  } catch {
    /* ignore */
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
  } catch {
    /* ignore */
  }
}

async function removeMember(employeeId: string): Promise<void> {
  const g = activeGroup.value;
  if (!g) return;
  try {
    const updated = await removeAiGroupMember(g.id, employeeId, 'admin');
    if (updated) {
      activeGroup.value = updated;
      groups.value = groups.value.map((x) => (x.id === updated.id ? updated : x));
    }
  } catch {
    /* ignore */
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
.aigc-msg__avatar { width: 34px; height: 34px; border-radius: 8px; background: #5b8def22; color: #3a5bb8; display: flex; align-items: center; justify-content: center; font-size: 13px; flex: none; overflow: hidden; }
.aigc-msg__avatar-img { width: 100%; height: 100%; display: block; object-fit: cover; }
.aigc-msg__col { display: flex; flex-direction: column; }
.aigc-msg__sender { font-size: 11px; color: var(--color-text-2, #999); margin: 0 2px 3px; }
.aigc-msg__bubble { padding: 9px 12px; border-radius: 10px; background: var(--color-surface, #fff); border: 1px solid var(--color-border-weak, #eee); font-size: 14px; line-height: 1.5; white-space: pre-wrap; word-break: break-word; }
.aigc-msg.is-user .aigc-msg__bubble { background: #95ec69; border-color: #7fd957; color: #1f2329; }
.aigc-msg__badge {
  display: inline-block;
  margin: 0 2px 4px;
  padding: 1px 7px;
  border-radius: 999px;
  font-size: 10px;
  font-weight: 600;
  color: #245bdb;
  background: #eef4ff;
  border: 1px solid #c9dcff;
}
.aigc-msg__badge.is-review { color: #b45309; background: #fff7ed; border-color: #fed7aa; }
.aigc-msg.is-discussion .aigc-msg__bubble { border-color: #7c3aed44; background: #faf5ff; }
.aigc-msg.is-routing .aigc-msg__bubble { border-color: #0d948844; background: #f0fdfa; }
.aigc-msg.is-work .aigc-msg__bubble { border-color: #5b8def55; background: #f7fbff; }
.aigc-msg.is-acceptance .aigc-msg__bubble { border-color: #16a34a55; background: #f0fdf4; }
.aigc-msg.is-acceptance-review .aigc-msg__bubble { border-color: #ea580c55; background: #fff7ed; }
.aigc-typing { font-size: 12px; color: var(--color-text-2, #999); }
.aigc-chat__input { display: flex; gap: 10px; padding: 12px 16px; border-top: 1px solid var(--color-border, #e5e7eb); background: var(--color-surface, #fff); }
.aigc-input { flex: 1; border: 1px solid var(--color-border, #ddd); border-radius: 8px; padding: 9px 12px; font-size: 14px; outline: none; }
.aigc-mode { border: 1px solid var(--color-border, #ddd); background: var(--color-surface, #fff); color: var(--color-text-1, #333); border-radius: 8px; padding: 0 12px; font-size: 13px; cursor: pointer; }
.aigc-mode.is-active { border-color: #3370ff; background: #eef4ff; color: #245bdb; font-weight: 600; }
.aigc-mode:disabled { color: #9ca3af; cursor: not-allowed; }
.aigc-send { padding: 0 18px; border: none; border-radius: 8px; background: #07c160; color: #fff; cursor: pointer; }
.aigc-send:disabled { background: #c8c9cc; cursor: not-allowed; }
.aigc-members { width: 240px; border-left: 1px solid var(--color-border, #e5e7eb); background: var(--color-surface, #fff); padding: 12px 14px; overflow-y: auto; }
.aigc-members__head { font-size: 12px; color: var(--color-text-2, #888); margin: 12px 0 6px; }
.aigc-member { display: flex; align-items: center; justify-content: space-between; width: 100%; padding: 8px 4px; border: none; background: none; border-bottom: 1px solid var(--color-border-weak, #f0f0f0); cursor: default; gap: 8px; }
.aigc-member__main { display: flex; align-items: center; gap: 8px; min-width: 0; }
.aigc-member__avatar { width: 28px; height: 28px; border-radius: 7px; background: #5b8def22; color: #3a5bb8; display: flex; align-items: center; justify-content: center; font-size: 12px; flex: none; overflow: hidden; }
.aigc-member__avatar-img { width: 100%; height: 100%; display: block; object-fit: cover; }
.aigc-member--add { cursor: pointer; }
.aigc-member__name { font-size: 13px; }
.aigc-member__add { color: #3370ff; }
.aigc-icon-btn { border: none; background: none; font-size: 18px; cursor: pointer; color: var(--color-text-2, #666); }
.aigc-text-btn { border: 1px solid var(--color-border, #ddd); background: none; border-radius: 6px; padding: 4px 10px; font-size: 12px; cursor: pointer; }
.aigc-text-btn--danger { color: #e34d59; border-color: #f0c2c5; }
.aigc-empty { color: var(--color-text-2, #999); font-size: 13px; padding: 20px; text-align: center; }
.aigc-empty--sm { padding: 8px; text-align: left; }
</style>
