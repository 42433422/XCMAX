<template>
  <aside :class="['im-sidebar', { 'im-sidebar--employees': isAdminCustomerServiceConsole }]">
    <div class="im-sidebar-head">
      <h2 class="im-title">信息</h2>
      <div class="im-sidebar-actions">
        <button type="button" class="im-icon-btn" title="发起会话" :disabled="busy" @click="emit('open-contact-picker')">
          <i class="fa fa-pencil-square-o" aria-hidden="true"></i>
        </button>
      </div>
    </div>

    <div class="im-conn" :class="imConnectionClass">
      <span class="im-conn-dot"></span>
      {{ imConnectionLabel }}
    </div>

    <div v-if="externalChannelEntries.length" class="im-channel-list">
      <button
        v-for="entry in externalChannelEntries"
        :key="entry.id"
        type="button"
        :class="['im-channel-entry', { active: activeExternalEntry?.id === entry.id }]"
        @click="emit('activate-pinned', entry)"
      >
        <span class="im-avatar im-avatar--channel" aria-hidden="true">客</span>
        <span class="im-conv-main">
          <span class="im-conv-title">{{ entry.display_name }}</span>
          <span class="im-conv-preview">{{ entry.subtitle }}</span>
        </span>
        <i class="fa fa-comments-o" aria-hidden="true"></i>
      </button>
    </div>

    <ul v-if="sidebarListItems.length" class="im-conv-list">
      <li v-for="item in sidebarListItems" :key="item.key" :class="sidebarItemClasses(item)" @click="emit('select-sidebar-item', item)">
        <span :class="sidebarItemAvatarClasses(item)" aria-hidden="true">
          <img
            v-if="sidebarItemSuperAvatarSrc(item)"
            class="im-super-tool-icon"
            :src="sidebarItemSuperAvatarSrc(item) || undefined"
            alt=""
            decoding="async"
            draggable="false"
          />
          <template v-else>{{ sidebarItemAvatarText(item) }}</template>
        </span>
        <div class="im-conv-main">
          <div class="im-conv-title">{{ sidebarItemTitle(item) }}</div>
          <div class="im-conv-preview">{{ sidebarItemPreview(item) }}</div>
        </div>
        <i v-if="sidebarItemShowsPin(item)" :class="sidebarItemPinClasses(item)" aria-hidden="true"></i>
        <span v-else-if="sidebarItemUnread(item) > 0" class="im-badge">
          {{ sidebarItemUnread(item) }}
        </span>
      </li>
    </ul>
    <div v-else class="im-empty im-empty--list">
      <i class="fa fa-comments-o" aria-hidden="true"></i>
      <p>还没有会话</p>
      <p class="im-empty-hint">这里联系已安装的 AI 同事和专属客服；找小C办事请用侧栏「智能对话」</p>
      <button type="button" class="im-btn im-btn--primary" :disabled="busy" @click="emit('open-contact-picker')">发起会话</button>
    </div>
  </aside>
</template>

<script setup lang="ts">
import { type ExternalAppEntry, type ImSidebarListItem, type PinnedImEntry } from '@/composables/messenger/useMessengerEntries'

defineProps<{
  isAdminCustomerServiceConsole: boolean
  busy: boolean
  imConnectionClass: string
  imConnectionLabel: string
  externalChannelEntries: ExternalAppEntry[]
  activeExternalEntry: ExternalAppEntry | null
  sidebarListItems: ImSidebarListItem[]
  sidebarItemClasses: (item: ImSidebarListItem) => unknown[]
  sidebarItemAvatarClasses: (item: ImSidebarListItem) => unknown[]
  sidebarItemPinClasses: (item: ImSidebarListItem) => unknown[]
  sidebarItemShowsPin: (item: ImSidebarListItem) => boolean
  sidebarItemTitle: (item: ImSidebarListItem) => string
  sidebarItemPreview: (item: ImSidebarListItem) => string
  sidebarItemAvatarText: (item: ImSidebarListItem) => string
  sidebarItemSuperAvatarSrc: (item: ImSidebarListItem) => string | null
  sidebarItemUnread: (item: ImSidebarListItem) => number
}>()

const emit = defineEmits<{
  (e: 'open-contact-picker'): void
  (e: 'activate-pinned', entry: PinnedImEntry): void
  (e: 'select-sidebar-item', item: ImSidebarListItem): void
}>()
</script>

<style scoped>
/* 左侧会话栏 */
.im-sidebar {
  width: 280px;
  border-right: 1px solid var(--xc-color-border, #e6e9ef);
  display: flex;
  flex-direction: column;
  background: #fafbfc;
  min-height: 0;
}
.im-sidebar-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 16px 10px;
}
.im-sidebar-actions {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.im-sidebar-actions .im-icon-btn {
  text-decoration: none;
}
.im-title {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: var(--xc-color-text, #1f2329);
}
.im-icon-btn {
  width: 30px;
  height: 30px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: var(--xc-color-muted, #86909c);
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 15px;
  transition:
    background 150ms ease,
    color 150ms ease;
}
.im-icon-btn:hover {
  background: rgba(0, 82, 217, 0.08);
  color: var(--xc-color-primary, #0052d9);
}
.im-conn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 0 16px 10px;
  font-size: 12px;
  color: var(--xc-color-muted, #86909c);
}
.im-conn-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #c9cdd4;
}
.im-conn.is-on .im-conn-dot {
  background: #00b42a;
}
.im-conn.is-api-on .im-conn-dot {
  background: #2f7cf6;
}
.im-conn.is-off .im-conn-dot {
  background: #ff7d00;
}
.im-conn.is-error .im-conn-dot {
  background: #f53f3f;
}

.im-channel-list {
  padding: 0 8px 6px;
}
.im-channel-entry {
  display: flex;
  width: 100%;
  align-items: center;
  gap: 10px;
  padding: 10px;
  border: 1px solid rgba(15, 118, 110, 0.16);
  border-radius: 8px;
  background: rgba(15, 118, 110, 0.06);
  color: inherit;
  text-align: left;
  cursor: pointer;
  transition:
    background 150ms ease,
    border-color 150ms ease;
}
.im-channel-entry:hover,
.im-channel-entry.active {
  border-color: rgba(15, 118, 110, 0.34);
  background: rgba(15, 118, 110, 0.12);
}
.im-channel-entry > .fa {
  color: #0f766e;
}
.im-avatar--channel {
  background: #dff3ee;
  color: #0f766e;
}

.im-conv-list {
  list-style: none;
  margin: 0;
  padding: 4px 8px;
  overflow-y: auto;
  flex: 1;
}
.im-sidebar--employees > .im-conv-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}
.im-conv-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px;
  border-radius: 8px;
  cursor: pointer;
  position: relative;
  transition: background 150ms ease;
}
.im-conv-item:hover {
  background: rgba(0, 0, 0, 0.035);
}
.im-conv-item.active {
  background: rgba(0, 82, 217, 0.08);
}
.im-conv-item--pinned {
  background: rgba(0, 82, 217, 0.05);
}
.im-conv-item--admin-contact {
  background: transparent;
}
.im-conv-item--admin-contact:hover {
  background: rgba(0, 0, 0, 0.035);
}
.im-conv-item--admin-contact.active {
  background: rgba(0, 82, 217, 0.08);
}
.im-pin {
  flex: none;
  color: var(--xc-color-primary, #0052d9);
  font-size: 12px;
}
.im-pin--employee {
  color: #86909c;
}
.im-pin--external {
  color: #0f766e;
}
.im-pin--group {
  color: #7c3aed;
}
.im-conv-main {
  min-width: 0;
  flex: 1;
}
.im-conv-title {
  font-weight: 500;
  font-size: 14px;
  color: var(--xc-color-text, #1f2329);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.im-conv-preview {
  font-size: 12px;
  color: var(--xc-color-muted, #86909c);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.im-badge {
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: #f53f3f;
  color: #fff;
  font-size: 11px;
  border-radius: 9px;
}

/* 头像 */
.im-avatar {
  flex: none;
  flex-basis: 38px;
  width: 38px;
  height: 38px;
  min-width: 38px;
  min-height: 38px;
  aspect-ratio: 1;
  border-radius: 50%;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  background: linear-gradient(135deg, #5b8def, #0052d9);
  color: #fff;
  font-size: 15px;
  font-weight: 600;
}
.im-avatar--super-tool {
  border-radius: 10px;
  background: transparent;
  font-size: 0;
  letter-spacing: 0;
  text-transform: none;
}
.im-avatar--sm.im-avatar--super-tool {
  flex-basis: 30px;
  width: 30px;
  height: 30px;
  min-width: 30px;
  min-height: 30px;
  border-radius: 8px;
}
.im-avatar--employee {
  border-radius: 10px;
  background: #edf4ff;
  color: #1f6feb;
}
.im-avatar--external {
  border-radius: 10px;
  background: #e6f6f2;
  color: #0f766e;
}
.im-avatar--group {
  border-radius: 10px;
  background: #f3e8ff;
  color: #7c3aed;
}
.im-avatar--sm.im-avatar--employee {
  flex-basis: 30px;
  width: 30px;
  height: 30px;
  min-width: 30px;
  min-height: 30px;
  border-radius: 8px;
}
.im-avatar--sm {
  flex-basis: 30px;
  width: 30px;
  height: 30px;
  min-width: 30px;
  min-height: 30px;
  font-size: 13px;
}
.im-super-tool-icon {
  width: 100%;
  height: 100%;
  display: block;
  object-fit: contain;
  border-radius: inherit;
  user-select: none;
  -webkit-user-drag: none;
}

/* 空状态 */
.im-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  flex: 1;
  padding: 24px;
  color: var(--xc-color-muted, #86909c);
  text-align: center;
}
.im-empty .fa {
  font-size: 32px;
  opacity: 0.35;
}
.im-empty p {
  margin: 0;
  font-size: 13px;
}

.im-empty-hint {
  max-width: 260px;
  margin-top: 4px !important;
  font-size: 12px !important;
  color: var(--xc-color-disabled, #9ca3af);
  line-height: 1.5;
}

.im-btn {
  padding: 8px 16px;
  border: 1px solid var(--xc-color-border, #e6e9ef);
  border-radius: 8px;
  background: #fff;
  cursor: pointer;
  font: inherit;
  font-size: 14px;
}
.im-btn--primary {
  background: var(--xc-color-primary, #0052d9);
  color: #fff;
  border-color: var(--xc-color-primary, #0052d9);
}
.im-btn--primary:hover:not(:disabled) {
  background: var(--xc-color-primary-hover, #003cab);
}
.im-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
