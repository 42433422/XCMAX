enum ConversationType {
  pinnedCs,
  pinnedAssistant,
  pinnedCodex,
  pinnedCursor,
  pinnedClaude,
  pinnedTrae,
  aiTask,
  systemNotification,
}

extension ConversationTypeX on ConversationType {
  bool get usesPinnedAvatar {
    switch (this) {
      case ConversationType.pinnedCs:
      case ConversationType.pinnedAssistant:
      case ConversationType.pinnedCodex:
      case ConversationType.pinnedCursor:
      case ConversationType.pinnedClaude:
      case ConversationType.pinnedTrae:
        return true;
      case ConversationType.aiTask:
      case ConversationType.systemNotification:
        return false;
    }
  }

  bool get defaultOnline => this == ConversationType.pinnedCs;

  String? get superTool {
    switch (this) {
      case ConversationType.pinnedCodex:
        return 'Codex';
      case ConversationType.pinnedCursor:
        return 'Cursor';
      case ConversationType.pinnedClaude:
        return 'Claude';
      case ConversationType.pinnedTrae:
        return 'Trae';
      case ConversationType.pinnedCs:
      case ConversationType.pinnedAssistant:
      case ConversationType.aiTask:
      case ConversationType.systemNotification:
        return null;
    }
  }
}

enum ConversationFilter { all, pinned, aiTask, superEmployee, unread }

extension ConversationFilterX on ConversationFilter {
  String get label {
    switch (this) {
      case ConversationFilter.all:
        return '全部';
      case ConversationFilter.pinned:
        return '置顶';
      case ConversationFilter.aiTask:
        return '伙伴';
      case ConversationFilter.superEmployee:
        return '超员工';
      case ConversationFilter.unread:
        return '未读';
    }
  }
}

class ConversationItem {
  const ConversationItem({
    required this.id,
    required this.type,
    required this.title,
    required this.subtitle,
    required this.timestampText,
    this.timestampMs = 0,
    this.avatarUrl,
    this.unreadCount = 0,
    this.isOnline = false,
    this.isPinned = false,
    this.isHidden = false,
    this.isFollowed = true,
    this.badgeText,
    this.badgeColor,
  });

  final String id;
  final ConversationType type;
  final String title;
  final String subtitle;
  final String timestampText;
  final int timestampMs;
  final String? avatarUrl;
  final int unreadCount;
  final bool isOnline;
  final bool isPinned;
  final bool isHidden;
  final bool isFollowed;
  final String? badgeText;
  final int? badgeColor;
}

enum ChatRole { assistant, user, system }

enum ChatDeliveryStatus { sent, sending, failed }

class ChatMessage {
  const ChatMessage({
    required this.id,
    required this.conversationId,
    required this.role,
    required this.body,
    required this.timeText,
    this.senderName,
    this.senderAvatarUrl,
    this.hasEmployeeProfile = false,
    this.status = ChatDeliveryStatus.sent,
    this.quote,
    this.cacheTimestampMs = 0,
  });

  final String id;
  final String conversationId;
  final ChatRole role;
  final String body;
  final String timeText;
  final String? senderName;
  final String? senderAvatarUrl;
  final bool hasEmployeeProfile;
  final ChatDeliveryStatus status;
  final String? quote;
  final int cacheTimestampMs;
}

class AiGroupMember {
  const AiGroupMember({
    required this.employeeId,
    this.modId = '',
    required this.name,
    required this.summary,
    this.avatarUrl,
    this.avatarKey = '',
    this.required = false,
  });

  final String employeeId;
  final String modId;
  final String name;
  final String summary;
  final String? avatarUrl;
  final String avatarKey;
  final bool required;

  String get key => '$modId:$employeeId';
}

class AiGroupConversation {
  const AiGroupConversation({
    required this.id,
    required this.name,
    required this.memberCount,
    required this.members,
    this.preview = '',
    this.timestampText = '',
    this.unreadCount = 0,
    this.isPinned = false,
    this.isHidden = false,
    this.isFollowed = true,
  });

  final String id;
  final String name;
  final int memberCount;
  final List<AiGroupMember> members;
  final String preview;
  final String timestampText;
  final int unreadCount;
  final bool isPinned;
  final bool isHidden;
  final bool isFollowed;

  AiGroupConversation copyWith({
    String? id,
    String? name,
    int? memberCount,
    List<AiGroupMember>? members,
    String? preview,
    String? timestampText,
    int? unreadCount,
    bool? isPinned,
    bool? isHidden,
    bool? isFollowed,
  }) {
    return AiGroupConversation(
      id: id ?? this.id,
      name: name ?? this.name,
      memberCount: memberCount ?? this.memberCount,
      members: members ?? this.members,
      preview: preview ?? this.preview,
      timestampText: timestampText ?? this.timestampText,
      unreadCount: unreadCount ?? this.unreadCount,
      isPinned: isPinned ?? this.isPinned,
      isHidden: isHidden ?? this.isHidden,
      isFollowed: isFollowed ?? this.isFollowed,
    );
  }
}

enum AiGroupMessageRole { user, ai, system }

class AiGroupMessage {
  const AiGroupMessage({
    required this.id,
    required this.groupId,
    required this.role,
    required this.senderId,
    required this.senderName,
    this.senderAvatar,
    required this.body,
    required this.createdAt,
    this.kind = '',
    this.status = '',
    this.workOrderId = '',
  });

  final String id;
  final String groupId;
  final AiGroupMessageRole role;
  final String senderId;
  final String senderName;
  final String? senderAvatar;
  final String body;
  final String createdAt;
  final String kind;
  final String status;
  final String workOrderId;
}

class AiGroupPostResult {
  const AiGroupPostResult({
    this.group,
    this.messages = const [],
  });

  final AiGroupConversation? group;
  final List<AiGroupMessage> messages;
}

class AiGroupCandidate {
  const AiGroupCandidate({
    required this.employeeId,
    required this.modId,
    required this.name,
    this.avatarUrl,
    required this.summary,
    required this.departmentKey,
    required this.isSuper,
  });

  final String employeeId;
  final String modId;
  final String name;
  final String? avatarUrl;
  final String summary;
  final String departmentKey;
  final bool isSuper;

  String get key => '$modId:$employeeId';

  AiGroupMember toMember() {
    return AiGroupMember(
      employeeId: employeeId,
      modId: modId,
      name: name,
      summary: summary,
      avatarUrl: avatarUrl,
    );
  }
}

class GitBranchInfo {
  const GitBranchInfo({
    required this.name,
    required this.current,
    required this.remote,
  });

  final String name;
  final bool current;
  final bool remote;
}

class CsInfo {
  const CsInfo({
    required this.available,
    required this.name,
    this.avatar,
    required this.online,
  });

  final bool available;
  final String name;
  final String? avatar;
  final bool online;
}

class CsMessage {
  const CsMessage({
    required this.messageId,
    required this.sender,
    required this.body,
    required this.timestamp,
    this.msgType = 'text',
  });

  final String messageId;
  final String sender;
  final String body;
  final String timestamp;
  final String msgType;

  bool get isUser => sender == 'user';
}

class CsMessageResponse {
  const CsMessageResponse({
    required this.messageId,
    required this.requestId,
    required this.reply,
    required this.backend,
    required this.timestamp,
  });

  final String messageId;
  final int requestId;
  final String reply;
  final String backend;
  final String timestamp;
}
