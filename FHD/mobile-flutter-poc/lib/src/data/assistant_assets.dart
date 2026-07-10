import '../models/conversation.dart';

class AssistantSearchResult {
  const AssistantSearchResult({
    required this.answer,
    this.sources = const [],
    this.provider = '',
    this.query = '',
    this.warning = '',
  });

  final String answer;
  final List<ChatSource> sources;
  final String provider;
  final String query;
  final String warning;
}

class AssistantMemoryRecord {
  const AssistantMemoryRecord({
    required this.id,
    required this.type,
    required this.key,
    required this.value,
    required this.status,
    this.updatedAt = '',
  });

  final String id;
  final String type;
  final String key;
  final String value;
  final String status;
  final String updatedAt;

  bool get isActive => status == 'active';
}

class AssistantFileAnalysis {
  const AssistantFileAnalysis({
    required this.filename,
    required this.employeeId,
    required this.summary,
    this.filePath = '',
  });

  final String filename;
  final String employeeId;
  final String summary;
  final String filePath;
}

class AssistantEmployeeAvailability {
  const AssistantEmployeeAvailability({
    required this.onlineConversationIds,
    this.desktopLabel = '',
    this.checkedAt = '',
  });

  final Set<String> onlineConversationIds;
  final String desktopLabel;
  final String checkedAt;

  bool isOnline(String conversationId) =>
      onlineConversationIds.contains(conversationId);

  bool get hasAny => onlineConversationIds.isNotEmpty;
}
