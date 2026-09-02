part of 'message_list_screen.dart';

// 会话排序、置顶判定与索引条目等工具函数。
List<Object> _sortMessageEntries(
  List<AiGroupConversation> groups,
  List<ConversationItem> items,
) {
  final entries = <_IndexedMessageEntry>[
    for (var i = 0; i < groups.length; i++)
      _IndexedMessageEntry(index: i, entry: groups[i]),
    for (var i = 0; i < items.length; i++)
      _IndexedMessageEntry(index: groups.length + i, entry: items[i]),
  ];
  entries.sort((a, b) {
    final aPinned = _messageEntryPinned(a.entry);
    final bPinned = _messageEntryPinned(b.entry);
    if (aPinned != bPinned) return aPinned ? -1 : 1;
    final timestampOrder = _messageEntryTimestampMs(
      b.entry,
    ).compareTo(_messageEntryTimestampMs(a.entry));
    if (timestampOrder != 0) return timestampOrder;
    return a.index.compareTo(b.index);
  });
  return entries.map((entry) => entry.entry).toList(growable: false);
}

bool _messageEntryPinned(Object entry) {
  if (entry is AiGroupConversation) return entry.isPinned;
  if (entry is ConversationItem) return entry.isPinned;
  return false;
}

int _messageEntryTimestampMs(Object entry) {
  if (entry is AiGroupConversation) return entry.timestampMs;
  if (entry is ConversationItem) return entry.timestampMs;
  return 0;
}

String? _visibleConversationBadge(ConversationItem item) {
  final badge = item.badgeText?.trim();
  if (badge == null || badge.isEmpty || badge == item.timestampText) {
    return null;
  }
  if (const {'管理端后台', '服务器后台'}.contains(badge)) return null;
  return badge;
}

class _IndexedMessageEntry {
  const _IndexedMessageEntry({required this.index, required this.entry});

  final int index;
  final Object entry;
}

String _textOrFallback(String value, String fallback) {
  final trimmed = value.trim();
  return trimmed.isEmpty ? fallback : trimmed;
}
