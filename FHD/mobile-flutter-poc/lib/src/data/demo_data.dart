import '../models/conversation.dart';
import '../policy/pinned_ids.dart';
import 'duty_roster_ssot.dart';

final demoConversations = <ConversationItem>[
  const ConversationItem(
    id: PinnedIds.assistant,
    type: ConversationType.pinnedAssistant,
    title: '小C助理',
    subtitle: '你好！目前 Codex 任务已经排队，我会继续同步进度。',
    timestampText: '现在',
    unreadCount: 2,
    isPinned: true,
  ),
  const ConversationItem(
    id: PinnedIds.codex,
    type: ConversationType.pinnedCodex,
    title: '超级员工-Codex',
    subtitle: '已读取 Android 头像策略，准备继续执行移动端任务。',
    timestampText: '03:07',
    unreadCount: 8,
    isPinned: true,
    badgeText: '群',
  ),
  const ConversationItem(
    id: PinnedIds.cursor,
    type: ConversationType.pinnedCursor,
    title: '超级员工-Cursor',
    subtitle: '可作为工程协作执行端，但头像固定用 Cursor 资源。',
    timestampText: '6/24',
    isPinned: true,
    badgeText: '群',
  ),
  const ConversationItem(
    id: PinnedIds.claude,
    type: ConversationType.pinnedClaude,
    title: '超级员工-Claude',
    subtitle: '负责分析、编写和任务复盘。',
    timestampText: '6/24',
    isPinned: true,
    badgeText: '群',
  ),
  const ConversationItem(
    id: PinnedIds.trae,
    type: ConversationType.pinnedTrae,
    title: '超级员工-Trae',
    subtitle: 'IDE 执行端、备用额度和补位协作。',
    timestampText: '6/23',
    isPinned: true,
    badgeText: '群',
  ),
  ...adminDutyRosterConversationItems(),
];
