/**
 * IM 信息页「左侧会话栏」的侧栏列表派生与选中逻辑。
 *
 * 纯响应式派生（不持有可变状态）：入参为父组件持有的各 ref 与回调，
 * 返回侧栏列表渲染所需的全部 computeds/函数。父组件通过
 * selectConversation / activatePinnedEntry 回调驱动会话切换。
 */
import { computed, type Ref } from 'vue';
import { type ImContact, type ImConversationSummary } from '@/api/im';
import {
  CLAUDE_SUPER_EMPLOYEE_ENTRY,
  CODEX_SUPER_EMPLOYEE_ENTRY,
  CURSOR_SUPER_EMPLOYEE_ENTRY,
  KELLAI_CUSTOMER_IM_ENTRY,
  SUPER_CLI_TOOLS,
  avatarText,
  isAiGroupChatEntry,
  isDutyEmployeeEntry,
  isEnterpriseDedicatedContact,
  isEnterpriseDedicatedConversation,
  isExternalAppEntry,
  isSuperEmployeeEntry,
  pinnedAvatarText,
  pinnedEntryPreview,
  superCliToolLabel,
  superEmployeeAvatarKey,
  superEmployeeAvatarSrc,
  type DutyEmployeeEntry,
  type ExternalAppEntry,
  type ImSidebarListItem,
  type PinnedImEntry,
  type SystemEmployeeEntry,
} from './useMessengerEntries';

export type UseConversationListParams = {
  conversations: Ref<ImConversationSummary[]>;
  contacts: Ref<ImContact[]>;
  dutyEmployees: Ref<DutyEmployeeEntry[]>;
  activeConversationId: Ref<number | null>;
  activeSystemEntry: Ref<SystemEmployeeEntry | null>;
  activeExternalEntry: Ref<ExternalAppEntry | null>;
  activeGroupChat: Ref<boolean>;
  isAdminCustomerServiceConsole: Ref<boolean>;
  selectConversation: (id: number) => Promise<void>;
  activatePinnedEntry: (entry: PinnedImEntry) => Promise<void>;
};

export function useConversationList(params: UseConversationListParams) {
  const {
    conversations,
    contacts,
    dutyEmployees,
    activeConversationId,
    activeSystemEntry,
    activeExternalEntry,
    activeGroupChat,
    isAdminCustomerServiceConsole,
    selectConversation,
    activatePinnedEntry,
  } = params;

  function existingDedicatedConversation(contact: ImContact): ImConversationSummary | undefined {
    const username = contact.username.trim().toLowerCase();
    return conversations.value.find((c) => {
      if (c.is_enterprise_dedicated_cs) return true;
      return username && c.title.trim().toLowerCase() === contact.display_name.trim().toLowerCase();
    });
  }

  const visibleConversations = computed(() =>
    conversations.value.filter(
      (c) => !isAdminCustomerServiceConsole.value || !isEnterpriseDedicatedConversation(c),
    ),
  );

  const pinnedContacts = computed<PinnedImEntry[]>(() => {
    if (isAdminCustomerServiceConsole.value) {
      return [CODEX_SUPER_EMPLOYEE_ENTRY, CURSOR_SUPER_EMPLOYEE_ENTRY, CLAUDE_SUPER_EMPLOYEE_ENTRY, ...dutyEmployees.value];
    }
    return [...contacts.value.filter((c) => isEnterpriseDedicatedContact(c))];
  });

  const externalChannelEntries = computed<ExternalAppEntry[]>(() => [
    // 企业端与管理端信息列表顶部均展示客来来客户通道
    KELLAI_CUSTOMER_IM_ENTRY,
  ]);

  const sidebarListItems = computed<ImSidebarListItem[]>(() => {
    const pinnedConversationIds = new Set<number>();
    for (const entry of pinnedContacts.value) {
      if (isSuperEmployeeEntry(entry) || isDutyEmployeeEntry(entry) || isExternalAppEntry(entry) || isAiGroupChatEntry(entry)) {
        continue;
      }
      const conv = existingDedicatedConversation(entry);
      if (conv) pinnedConversationIds.add(conv.id);
    }
    return [
      ...pinnedContacts.value.map((entry) => ({
        kind: 'pinned' as const,
        key: `pinned-${entry.id}`,
        entry,
      })),
      ...visibleConversations.value
        .filter((conversation) => !pinnedConversationIds.has(conversation.id))
        .map((conversation) => ({
          kind: 'conversation' as const,
          key: `conversation-${conversation.id}`,
          conversation,
        })),
    ];
  });

  const superCliTools = computed(() =>
    isAdminCustomerServiceConsole.value ? SUPER_CLI_TOOLS : [],
  );

  function isPinnedContactActive(contact: PinnedImEntry): boolean {
    if (isExternalAppEntry(contact)) return activeExternalEntry.value?.id === contact.id;
    if (isAiGroupChatEntry(contact)) return activeGroupChat.value;
    if (isSuperEmployeeEntry(contact)) {
      return activeSystemEntry.value?.id === contact.id;
    }
    if (isDutyEmployeeEntry(contact)) {
      return activeSystemEntry.value?.id === contact.id;
    }
    const conv = existingDedicatedConversation(contact);
    return !!conv && conv.id === activeConversationId.value;
  }

  function isSidebarItemActive(item: ImSidebarListItem): boolean {
    return item.kind === 'pinned'
      ? isPinnedContactActive(item.entry)
      : item.conversation.id === activeConversationId.value;
  }

  function sidebarItemClasses(item: ImSidebarListItem) {
    return [
      'im-conv-item',
      { 'im-conv-item--pinned': item.kind === 'pinned' },
      { 'im-conv-item--admin-contact': item.kind === 'pinned' && isAdminCustomerServiceConsole.value },
      { active: isSidebarItemActive(item) },
    ];
  }

  function sidebarItemAvatarClasses(item: ImSidebarListItem) {
    if (item.kind === 'conversation') return ['im-avatar'];
    const entry = item.entry;
    const avatarKey = superEmployeeAvatarKey(entry);
    return [
      'im-avatar',
      {
        'im-avatar--super-tool': avatarKey,
        [`im-avatar--${avatarKey}`]: avatarKey,
        'im-avatar--employee': isDutyEmployeeEntry(entry),
        'im-avatar--external': isExternalAppEntry(entry),
        'im-avatar--group': isAiGroupChatEntry(entry),
      },
    ];
  }

  function sidebarItemPinClasses(item: ImSidebarListItem) {
    if (item.kind !== 'pinned') return [];
    return [
      'fa',
      isAiGroupChatEntry(item.entry)
        ? 'fa-users'
        : isExternalAppEntry(item.entry)
          ? 'fa-comments-o'
          : isDutyEmployeeEntry(item.entry)
            ? 'fa-id-badge'
            : 'fa-thumb-tack',
      'im-pin',
      {
        'im-pin--group': isAiGroupChatEntry(item.entry),
        'im-pin--employee': isDutyEmployeeEntry(item.entry),
        'im-pin--external': isExternalAppEntry(item.entry),
      },
    ];
  }

  function sidebarItemShowsPin(item: ImSidebarListItem): boolean {
    return item.kind === 'pinned' && (isExternalAppEntry(item.entry) || !isAdminCustomerServiceConsole.value);
  }

  function sidebarItemTitle(item: ImSidebarListItem): string {
    return item.kind === 'pinned' ? item.entry.display_name : item.conversation.title;
  }

  function sidebarItemPreview(item: ImSidebarListItem): string {
    return item.kind === 'pinned'
      ? pinnedEntryPreview(item.entry)
      : item.conversation.last_message_preview || '暂无消息';
  }

  function sidebarItemAvatarText(item: ImSidebarListItem): string {
    return item.kind === 'pinned'
      ? pinnedAvatarText(item.entry)
      : avatarText(item.conversation.title);
  }

  function sidebarItemSuperAvatarSrc(item: ImSidebarListItem): string | null {
    return item.kind === 'pinned' ? superEmployeeAvatarSrc(item.entry) : null;
  }

  function sidebarItemUnread(item: ImSidebarListItem): number {
    return item.kind === 'conversation' ? item.conversation.unread_count || 0 : 0;
  }

  function selectSidebarItem(item: ImSidebarListItem): void {
    if (item.kind === 'pinned') {
      void activatePinnedEntry(item.entry);
      return;
    }
    void selectConversation(item.conversation.id);
  }

  return {
    existingDedicatedConversation,
    visibleConversations,
    pinnedContacts,
    externalChannelEntries,
    sidebarListItems,
    superCliTools,
    superCliToolLabel,
    isPinnedContactActive,
    isSidebarItemActive,
    sidebarItemClasses,
    sidebarItemAvatarClasses,
    sidebarItemPinClasses,
    sidebarItemShowsPin,
    sidebarItemTitle,
    sidebarItemPreview,
    sidebarItemAvatarText,
    sidebarItemSuperAvatarSrc,
    sidebarItemUnread,
    selectSidebarItem,
  };
}