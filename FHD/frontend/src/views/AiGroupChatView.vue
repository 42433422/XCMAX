<template>
  <div class="aigc">
    <!-- 左：群列表 -->
    <aside v-if="!group" class="aigc-list">
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
          <GroupAvatar :name="g.name" :members="g.members" />
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
      <div v-if="chatError || transport.error.value" class="aigc-error" role="alert">
        {{ chatError || transport.error.value }}
        <button class="aigc-text-btn" :disabled="sending" @click="selectGroup(activeGroup)">重新连接</button>
      </div>

      <p v-if="receiptError" class="aigc-error" role="status">{{ receiptError }}</p>
      <MatureChat :room-id="activeGroup.id" :title="activeGroup.name"
        :subtitle="`${activeGroup.member_count} 个 AI 成员${transport.active.value ? (transport.connected.value ? ' · 已连接' : ' · 连接中') : ''}`"
        :rows="chatRows" v-model:draft="input" :disabled="sending || !sessionAvailable"
        :busy-label="sending ? sendingLabel : '正在连接…'" :has-more="transport.hasOlder.value" :placeholder="inputPlaceholder"
        @send="send" @load-older="loadOlder">
        <template #avatar><GroupAvatar :name="activeGroup.name" :members="activeGroup.members" /></template>
        <template #actions>
          <button class="aigc-text-btn" :class="{ 'is-active': dispatchMode }" :aria-pressed="dispatchMode" :disabled="sending" @click="dispatchMode = !dispatchMode">派工</button>
          <button class="aigc-text-btn" :aria-expanded="showMembers" @click="showMembers = !showMembers">群成员</button>
        </template>
      </MatureChat>
    </section>
    <section class="aigc-chat aigc-chat--empty" v-else>
      <div class="aigc-empty">选择左侧的群开始聊天</div>
    </section>

    <!-- 群成员抽屉 -->
    <aside class="aigc-members" v-if="showMembers && activeGroup">
      <div class="aigc-members__head">群成员（{{ activeGroup.member_count }}）<button class="aigc-text-btn" @click="showMembers = false">关闭</button></div>
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
import { computed, onMounted, ref, watch } from 'vue';
import { productReadAccountEpoch } from '@/utils/productReadAccountScope';
import MatureChat from '@/components/im/MatureChat.vue';
import GroupAvatar from '@/components/im/GroupAvatar.vue';
import { employeeAvatarUrl } from '@/utils/employeeAvatar';
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
import { useAiGroupResultRefresh } from '@/composables/messenger/useAiGroupResultRefresh';
import { useOpenIMGroup } from '@/composables/messenger/useOpenIMGroup';

type PickEmployee = { employee_id: string; mod_id: string; name: string; avatar: string; summary: string };

const props = defineProps<{ group?: AiGroup }>();
const emit = defineEmits<{ (event: 'group-updated', group: AiGroup): void }>();
const groups = ref<AiGroup[]>([]);
const activeGroup = ref<AiGroup | null>(null);
const messages = ref<AiGroupMessage[]>([]);
const employees = ref<PickEmployee[]>([]);
const input = ref('');
const sending = ref(false);
const loading = ref(false);
const sessionReady = ref(false);
let selection = 0;
const showMembers = ref(false);
const dispatchMode = ref(false);
const chatError = ref('');
function mergeMessages(rows: AiGroupMessage[]) {
  const existing = messages.value.filter(m => !m.id.startsWith('local-') || !rows.some(row => row.role === 'user' && row.body === m.body));
  messages.value = [...new Map([...existing, ...rows].map(row => [row.id, row])).values()]
    .sort((a, b) => a.created_at.localeCompare(b.created_at));
}
const transport = useOpenIMGroup(mergeMessages);
const sessionAvailable = computed(() => sessionReady.value && !loading.value
  && (!transport.active.value || transport.connected.value));
const receiptError = useAiGroupResultRefresh(() => activeGroup.value?.id || '',
  () => sessionAvailable.value, mergeMessages);
watch(productReadAccountEpoch, () => {
  selection++;
  activeGroup.value = null; groups.value = []; messages.value = []; input.value = ''; employees.value = [];
  loading.value = false; sending.value = false; sessionReady.value = false;
}, { flush: 'sync' });
const chatRows = computed(() => messages.value.map(m => ({ id: m.id, body: m.body,
  mine: m.role === 'user', sender: m.sender_name, avatar: messageAvatarSrc(m), at: m.created_at,
  label: messageUi(m).badge,
})));
async function loadOlder() {
  try { await transport.history(true); }
  catch { chatError.value = '历史消息加载失败，请重试'; }
}

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
  if (/^(https?:|data:|blob:|\/)/i.test(raw)) return raw;
  const base = String(import.meta.env.BASE_URL || '/');
  return `${base.replace(/\/$/, '')}/${raw.replace(/^\//, '')}`;
}

function memberAvatarSrc(member: AiGroupMember): string | null {
  const resolved = resolveSuperEmployeeAvatarSrc(member.employee_id, member.avatar) || employeeAvatarUrl(member.employee_id);
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
  const epoch = productReadAccountEpoch.value;
  try {
    const rows = await fetchAiGroups('admin');
    if (epoch !== productReadAccountEpoch.value) return;
    groups.value = rows;
    if (!activeGroup.value && groups.value.length) await selectGroup(groups.value[0]);
  } catch {
    /* 静默：保留旧值 */
  }
}

async function selectGroup(g: AiGroup): Promise<void> {
  const selected = ++selection;
  sessionReady.value = false;
  loading.value = true;
  sending.value = false;
  activeGroup.value = g;
  messages.value = [];
  chatError.value = '';
  try {
    const enabled = await transport.start(g.id);
    if (selected !== selection) return;
    if (!enabled) {
      const rows = await fetchAiGroupMessages(g.id, 'admin');
      if (selected !== selection) return;
      messages.value = rows;
    }
    sessionReady.value = true;
  } catch {
    if (selected === selection) chatError.value = '消息加载失败，请重新连接';
  } finally {
    if (selected === selection) loading.value = false;
  }
}

async function send(): Promise<void> {
  const text = input.value.trim();
  const g = activeGroup.value;
  if (!text || !g || sending.value || !sessionAvailable.value) return;
  const selected = selection;
  input.value = '';
  messages.value = [
    ...messages.value,
    { id: `local-${messages.value.length}`, group_id: g.id, role: 'user', sender_id: 'user', sender_name: '我', sender_avatar: '', body: text, created_at: new Date().toISOString() },
  ];
  sending.value = true;
  chatError.value = '';
  try {
    const res = await postAiGroupMessage(g.id, text, [], 'admin', { dispatch: dispatchMode.value });
    if (selected !== selection) return;
    messages.value = messages.value.filter((m) => !m.id.startsWith('local-'));
    mergeMessages(res.messages);
    if (res.group) {
      emit('group-updated', res.group);
      activeGroup.value = res.group;
      groups.value = groups.value.map((x) => (x.id === res.group!.id ? res.group! : x));
    }
  } catch {
    if (selected !== selection) return;
    messages.value = messages.value.filter((m) => !m.id.startsWith('local-'));
    input.value = text;
    chatError.value = '发送结果尚未确认，请重新连接核对消息，避免重复派工';
  } finally {
    if (selected === selection) sending.value = false;
  }
}

async function onCreateGroup(): Promise<void> {
  const epoch = productReadAccountEpoch.value;
  const name = window.prompt('群名称');
  if (!name || !name.trim()) return;
  try {
    await createAiGroup(name.trim(), 'admin');
    if (epoch === productReadAccountEpoch.value) await loadGroups();
  } catch {
    /* ignore */
  }
}

async function addMember(e: PickEmployee): Promise<void> {
  const g = activeGroup.value;
  if (!g) return;
  const selected = selection;
  try {
    const updated = await addAiGroupMember(g.id, e, 'admin');
    if (updated && selected === selection) {
      emit('group-updated', updated);
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
  const selected = selection;
  try {
    const updated = await removeAiGroupMember(g.id, employeeId, 'admin');
    if (updated && selected === selection) {
      emit('group-updated', updated);
      activeGroup.value = updated;
      groups.value = groups.value.map((x) => (x.id === updated.id ? updated : x));
    }
  } catch {
    /* ignore */
  }
}

async function loadEmployees(): Promise<void> {
  const epoch = productReadAccountEpoch.value;
  try {
    const res = await apiFetch('/api/mobile/v1/admin/employees', { headers: { 'Content-Type': 'application/json' } });
    const json = (await res.json()) as { data?: { items?: unknown[]; employees?: unknown[] }; items?: unknown[]; employees?: unknown[] };
    if (epoch !== productReadAccountEpoch.value) return;
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
    if (epoch === productReadAccountEpoch.value) employees.value = [];
  }
}

onMounted(() => {
  if (props.group) void selectGroup(props.group);
  else void loadGroups();
  loadEmployees();
});
</script>

<style scoped>
.aigc-error { padding: 8px 18px; background: var(--color-warning-soft, #fff7e6); font-size: 13px; }
.aigc { position:relative; display: flex; height: 100%; min-height: 0; background: var(--color-bg, #f5f6f7); }
.aigc-list { width: 280px; border-right: 1px solid var(--color-border, #e5e7eb); background: var(--color-surface, #fff); display: flex; flex-direction: column; }
.aigc-list__head { display: flex; align-items: center; justify-content: space-between; padding: 14px 16px; font-weight: 600; border-bottom: 1px solid var(--color-border, #e5e7eb); }
.aigc-list__body { overflow-y: auto; flex: 1; }
.aigc-group { display: flex; gap: 10px; align-items: center; width: 100%; padding: 12px 16px; border: none; background: none; cursor: pointer; text-align: left; border-bottom: 1px solid var(--color-border-weak, #f0f0f0); }
.aigc-group.is-active { background: var(--color-primary-soft, #eef4ff); }
.aigc-chat__identity { display:flex; align-items:center; gap:10px; min-width:0; }
.aigc-group__main { min-width: 0; }
.aigc-group__name { font-size: 14px; font-weight: 500; }
.aigc-group__sub { font-size: 12px; color: var(--color-text-2, #888); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.aigc-chat { flex: 1; display: flex; flex-direction: column; min-width: 0; }
.aigc-chat--empty { align-items: center; justify-content: center; }
.aigc-chat__head { display: flex; align-items: center; justify-content: space-between; padding: 12px 18px; border-bottom: 1px solid var(--color-border, #e5e7eb); background: var(--color-surface, #fff); }
.aigc-chat__title { font-weight: 600; }
.aigc-chat__sub { font-size: 12px; color: var(--color-text-2, #888); }
.aigc-members { position:absolute; z-index:3; right:0; top:64px; bottom:0; width:min(280px, 85%); box-sizing:border-box; box-shadow:-8px 0 24px #182b4910; border-left: 1px solid var(--color-border, #e5e7eb); background: var(--color-surface, #fff); padding: 12px 14px; overflow-y: auto; }
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
.aigc-text-btn.is-active { background:#e6efff; color:#245bdb; border-color:#c7d9ff; }
.aigc-text-btn--danger { color: #e34d59; border-color: #f0c2c5; }
.aigc-empty { color: var(--color-text-2, #999); font-size: 13px; padding: 20px; text-align: center; }
.aigc-empty--sm { padding: 8px; text-align: left; }
</style>
