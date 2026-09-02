part of 'mobile_repository.dart';

class _IndexedConversationItem {
  const _IndexedConversationItem({required this.index, required this.item});

  final int index;
  final ConversationItem item;
}

class _EmployeeConversationRef {
  const _EmployeeConversationRef({
    required this.modId,
    required this.employeeId,
  });

  final String modId;
  final String employeeId;
}

_EmployeeConversationRef? _employeeConversationRef(String raw) {
  final value = raw.trim();
  if (!value.startsWith('employee:')) return null;
  final parts = value.split(':');
  if (parts.length < 3) return null;
  final modId = parts[1].trim();
  final employeeId = parts[2].trim();
  if (modId.isEmpty || employeeId.isEmpty) return null;
  return _EmployeeConversationRef(modId: modId, employeeId: employeeId);
}

List<ConversationItem> _fixedConversationItems({
  required bool showCodex,
  required bool showCursor,
  required bool showClaude,
  required bool showTrae,
  required bool showCustomerService,
  required Map<String, _ConversationListState> states,
}) {
  final items = <ConversationItem>[
    ConversationItem(
      id: PinnedIds.assistant,
      type: ConversationType.pinnedAssistant,
      title: '小C助理',
      subtitle: states[PinnedIds.assistant]?.preview.ifEmpty('有什么可以帮您？') ??
          '有什么可以帮您？',
      timestampText: states[PinnedIds.assistant]?.timestampText ?? '',
      timestampMs: states[PinnedIds.assistant]?.timestampMs ?? 0,
      isPinned: true,
    ),
  ];

  if (showCodex) {
    final state = states[PinnedIds.codex];
    items.add(
      ConversationItem(
        id: PinnedIds.codex,
        type: ConversationType.pinnedCodex,
        title: '超级员工-Codex',
        subtitle: state?.preview.ifEmpty('全设备协同') ?? '全设备协同',
        timestampText: state?.timestampText ?? '',
        timestampMs: state?.timestampMs ?? 0,
        isOnline: true,
        isPinned: true,
      ),
    );
  }
  if (showCursor) {
    final state = states[PinnedIds.cursor];
    items.add(
      ConversationItem(
        id: PinnedIds.cursor,
        type: ConversationType.pinnedCursor,
        title: '超级员工-Cursor',
        subtitle: state?.preview.ifEmpty('全设备协同 · Agent') ?? '全设备协同 · Agent',
        timestampText: state?.timestampText ?? '',
        timestampMs: state?.timestampMs ?? 0,
        isOnline: true,
        isPinned: true,
      ),
    );
  }
  if (showClaude) {
    final state = states[PinnedIds.claude];
    items.add(
      ConversationItem(
        id: PinnedIds.claude,
        type: ConversationType.pinnedClaude,
        title: '超级员工-Claude',
        subtitle: state?.preview.ifEmpty('全设备协同 · 排比派工') ?? '全设备协同 · 排比派工',
        timestampText: state?.timestampText ?? '',
        timestampMs: state?.timestampMs ?? 0,
        isOnline: true,
        isPinned: true,
      ),
    );
  }
  if (showTrae) {
    final state = states[PinnedIds.trae];
    items.add(
      ConversationItem(
        id: PinnedIds.trae,
        type: ConversationType.pinnedTrae,
        title: '超级员工-Trae',
        subtitle: state?.preview.ifEmpty('全设备协同 · Trae') ?? '全设备协同 · Trae',
        timestampText: state?.timestampText ?? '',
        timestampMs: state?.timestampMs ?? 0,
        isOnline: true,
        isPinned: true,
      ),
    );
  }
  if (showCustomerService) {
    final state = states[PinnedIds.cs];
    items.add(
      ConversationItem(
        id: PinnedIds.cs,
        type: ConversationType.pinnedCs,
        title: '专属客服',
        subtitle: state?.preview.ifEmpty('您好，我是您的专属客服') ?? '您好，我是您的专属客服',
        timestampText: state?.timestampText ?? '',
        timestampMs: state?.timestampMs ?? 0,
        isOnline: true,
        isPinned: true,
      ),
    );
  }

  return items;
}

class _ConversationListState {
  const _ConversationListState({
    required this.preview,
    required this.timestampMs,
  });

  final String preview;
  final int timestampMs;

  String get timestampText => _friendlyTimestampFromMillis(timestampMs);

  Map<String, Object?> toJson() => {
        'last_message_preview': preview,
        'last_message_at': timestampMs,
      };

  static _ConversationListState? fromJson(Map<String, Object?> json) {
    final timestamp = _firstPositiveInt([
      json['last_message_at'],
      json['timestamp_ms'],
      json['timestamp'],
      json['ts'],
    ]);
    final preview = _firstNonBlank([
      _stringField(json, 'last_message_preview'),
      _stringField(json, 'preview'),
      _stringField(json, 'body'),
    ]);
    if (timestamp <= 0 && preview.isEmpty) return null;
    return _ConversationListState(preview: preview, timestampMs: timestamp);
  }
}

Future<Map<String, _ConversationListState>> _loadConversationListStates(
  MobileApiClient client,
) async {
  final session = await client.loadSession();
  final result = <String, _ConversationListState>{};
  for (final entry in session.conversationListStates.entries) {
    final key = entry.key.trim();
    if (key.isEmpty) continue;
    final state = _ConversationListState.fromJson(entry.value);
    if (state != null) result[key] = state;
  }
  return result;
}

String _conversationPreviewForRole(ChatRole role, String text) {
  final normalized = text.trim().replaceAll('\n', ' ').replaceAll('\r', ' ');
  if (normalized.isEmpty) return '';
  switch (role) {
    case ChatRole.user:
      return '我: $normalized';
    case ChatRole.assistant:
    case ChatRole.system:
      return normalized;
  }
}

int _firstPositiveInt(List<Object?> values) {
  for (final value in values) {
    if (value is int && value > 0) return value;
    if (value is num && value > 0) return value.toInt();
    if (value is String) {
      final parsed = int.tryParse(value.trim());
      if (parsed != null && parsed > 0) return parsed;
    }
  }
  return 0;
}

const _emptyConversationStates = <String, _ConversationListState>{};
