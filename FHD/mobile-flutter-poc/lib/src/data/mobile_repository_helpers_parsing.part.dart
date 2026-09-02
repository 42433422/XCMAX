part of 'mobile_repository.dart';

String _firstNonBlank(List<String> values) {
  for (final value in values) {
    final trimmed = value.trim();
    if (trimmed.isNotEmpty) return trimmed;
  }
  return '';
}

String _pairingLanBaseUrl(String host, int port) {
  final hostWithPort = _compactPairingHostPort(host, port);
  if (hostWithPort.isEmpty) return '';
  return 'http://$hostWithPort/';
}

String _pairingLanBaseUrlFromHostPort(String hostWithPort) {
  final normalized = _normalizePairingHost(hostWithPort);
  if (normalized.isEmpty) return '';
  final parts = normalized.split(':');
  final host = parts.first.trim();
  if (host.isEmpty) return '';
  int port = 0;
  if (parts.length > 1) {
    port = (int.tryParse(parts.last.trim()) ?? 0).takeIfValidPort();
  }
  final cleanPort = port > 0 ? port : MobileBuildConfig.fhdDefaultPort;
  return 'http://$host:$cleanPort/';
}

String _hostPortFromApiBaseUrl(String raw) {
  final (host, port) = _pairingHostPortFromApiBase(raw);
  return _compactPairingHostPort(host, port);
}

String _readStringMap(Map<String, Object?>? data, List<String> keys) {
  if (data == null || data.isEmpty) return '';
  for (final key in keys) {
    final value = data[key]?.toString().trim() ?? '';
    if (value.isNotEmpty) return value;
  }
  return '';
}

String _compactPairingHostPort(String host, int port) {
  final bare = _normalizePairingHost(host).split(':').first.trim();
  final cleanPort = port.takeIfValidPort();
  if (bare.isEmpty) return '';
  if (cleanPort == 0) return bare;
  return '$bare:$cleanPort';
}

String _normalizePairingHost(String host) {
  return host
      .trim()
      .replaceFirst(RegExp(r'^https?://'), '')
      .split('/')
      .first
      .trim();
}

int _pairingPort(Map<String, Object?> json, String host) {
  final explicit = _intField(json, 'port').takeIfValidPort();
  if (explicit > 0) return explicit;
  if (!host.contains(':')) return 0;
  return (int.tryParse(host.split(':').last.trim()) ?? 0).takeIfValidPort();
}

(String, int) _pairingHostPortFromApiBase(String raw) {
  if (raw.trim().isEmpty) return ('', 0);
  final normalized = raw.contains('://') ? raw.trim() : 'http://${raw.trim()}';
  final uri = Uri.tryParse(normalized);
  if (uri == null) return ('', 0);
  final host = uri.host.trim();
  if (host.isEmpty) return ('', 0);
  final port = uri.hasPort
      ? uri.port.takeIfValidPort()
      : switch (uri.scheme.toLowerCase()) {
          'https' => 443,
          'http' => 80,
          _ => 0,
        };
  return (host, port);
}

String _relayIdFromBindingData(Map<String, Object?>? data) {
  final payload = data ?? const <String, Object?>{};
  return _firstNonBlank([
    _stringField(payload, 'relay_id'),
    _stringField(_objectMap(payload['relay']), 'relay_id'),
    _stringField(_objectMap(payload['desktop']), 'relay_id'),
  ]);
}

List<AiGroupConversation> _parseAiGroups(Object? value) {
  final data = _objectMap(value);
  final rawGroups = data['groups'] ?? data['items'] ?? data['data'] ?? value;
  return _objectList(rawGroups)
      .map(_aiGroupFromJson)
      .where((group) => group.id.trim().isNotEmpty)
      .toList(growable: false);
}

AiGroupConversation _aiGroupFromJson(Map<String, Object?> json) {
  final lastMessageAt = _stringField(json, 'last_message_at');
  return AiGroupConversation(
    id: _stringField(json, 'id'),
    name: _stringField(json, 'name'),
    memberCount: _intField(json, 'member_count'),
    preview: _aiGroupPreview(_stringField(json, 'last_message_preview')),
    timestampText: _friendlyGroupTimestamp(lastMessageAt),
    timestampMs: _timestampMsFromValue(json['last_message_at']),
    unreadCount: _intField(json, 'unread_count'),
    isPinned: _boolField(json, 'is_pinned'),
    isHidden: _boolField(json, 'is_hidden'),
    isFollowed: _boolField(json, 'is_followed', fallback: true),
    members: _objectList(json['members'])
        .map(
          (member) => AiGroupMember(
            employeeId: _stringField(member, 'employee_id'),
            modId: _stringField(member, 'mod_id'),
            name: _stringField(member, 'name'),
            summary: _stringField(member, 'summary'),
            avatarUrl: _stringField(member, 'avatar').ifEmpty(''),
            avatarKey: _stringField(member, 'avatar_key'),
          ),
        )
        .toList(growable: false),
  );
}

int _timestampMsFromValue(Object? value) {
  if (value is int) return value;
  if (value is num) return value.toInt();
  if (value is String) {
    final trimmed = value.trim();
    if (trimmed.isEmpty) return 0;
    final numeric = int.tryParse(trimmed);
    if (numeric != null) return numeric;
    final parsed = DateTime.tryParse(trimmed);
    if (parsed != null) return parsed.toLocal().millisecondsSinceEpoch;
  }
  return 0;
}

String _aiGroupPreview(String raw) {
  final text = raw.trim();
  if (text.isEmpty) return '';
  if (text.contains('服务器队列') ||
      text.contains('任务仍在后台运行') ||
      (text.contains('状态：排队中') && text.contains('任务号'))) {
    return '';
  }
  return text;
}

AiGroupConversation? _groupFromWrap(Map<String, Object?>? body) {
  final data = _nestedDataMap(body ?? const <String, Object?>{});
  final group = _objectMap(data['group']);
  if (group.isNotEmpty) return _aiGroupFromJson(group);
  if (data['id'] != null) return _aiGroupFromJson(data);
  return null;
}

List<AiGroupMessage> _parseAiGroupMessages(Object? value) {
  final data = _objectMap(value);
  final raw = data['messages'] ?? data['items'] ?? data['data'] ?? value;
  return _objectList(raw)
      .map(_aiGroupMessageFromJson)
      .where(
        (message) =>
            message.id.trim().isNotEmpty || message.body.trim().isNotEmpty,
      )
      .toList(growable: false);
}

AiGroupPostResult _parseAiGroupPostResult(Map<String, Object?>? body) {
  final data = _nestedDataMap(body ?? const <String, Object?>{});
  return AiGroupPostResult(
    group: _groupFromWrap(data),
    messages: _parseAiGroupMessages(data),
  );
}

AiGroupMessage _aiGroupMessageFromJson(Map<String, Object?> json) {
  final role = _stringField(json, 'role').trim().toLowerCase();
  return AiGroupMessage(
    id: _stringField(json, 'id'),
    groupId: _stringField(json, 'group_id'),
    role: role == 'user'
        ? AiGroupMessageRole.user
        : role == 'system'
            ? AiGroupMessageRole.system
            : AiGroupMessageRole.ai,
    senderId: _stringField(json, 'sender_id'),
    senderName: _stringField(json, 'sender_name').ifEmpty('AI员工'),
    senderAvatar: _nullableStringField(json, 'sender_avatar'),
    body: _firstNonBlank([
      _stringField(json, 'body'),
      _stringField(json, 'message'),
      _stringField(json, 'content'),
    ]),
    createdAt: _firstNonBlank([
      _stringField(json, 'created_at'),
      _stringField(json, 'timestamp'),
      '刚刚',
    ]),
    kind: _stringField(json, 'kind'),
    status: _stringField(json, 'status'),
    workOrderId: _stringField(json, 'work_order_id'),
  );
}

List<AiGroupCandidate> _parseAiGroupCandidates(Object? value) {
  final data = _objectMap(value);
  final raw = data['candidates'] ?? data['items'] ?? data['data'] ?? value;
  return _objectList(raw)
      .map(
        (json) => AiGroupCandidate(
          employeeId: _stringField(json, 'employee_id'),
          modId: _stringField(json, 'mod_id'),
          name: _stringField(json, 'name').ifEmpty('AI员工'),
          avatarUrl: _nullableStringField(json, 'avatar'),
          summary: _stringField(json, 'summary'),
          departmentKey: _stringField(json, 'department_key'),
          isSuper: _boolField(json, 'is_super'),
        ),
      )
      .where((candidate) => candidate.employeeId.trim().isNotEmpty)
      .toList(growable: false);
}

List<GitBranchInfo> _parseGitBranches(Object? value) {
  final data = _objectMap(value);
  final raw = data['branches'] ?? data['items'] ?? data['data'] ?? value;
  return _objectList(raw)
      .map(
        (json) => GitBranchInfo(
          name: _stringField(json, 'name'),
          current: _boolField(json, 'current'),
          remote: _boolField(json, 'remote'),
        ),
      )
      .where((branch) => branch.name.trim().isNotEmpty)
      .toList(growable: false);
}

CsInfo _parseCsInfo(Object? value) {
  final data = _objectMap(value);
  return CsInfo(
    available: _boolField(data, 'cs_available'),
    name: _stringField(data, 'cs_name').ifEmpty('专属客服'),
    avatar: _nullableStringField(data, 'cs_avatar'),
    online: _boolField(data, 'cs_online'),
  );
}

List<CsMessage> _parseCsMessages(Object? value) {
  final data = _objectMap(value);
  final raw = data['messages'] ?? data['items'] ?? data['data'] ?? value;
  return _objectList(raw)
      .map(
        (json) => CsMessage(
          messageId: _stringField(
            json,
            'message_id',
          ).ifEmpty(_stringField(json, 'id')),
          sender: _stringField(json, 'sender'),
          body: _firstNonBlank([
            _stringField(json, 'body'),
            _stringField(json, 'content'),
            _stringField(json, 'text'),
          ]),
          timestamp: _firstNonBlank([
            _stringField(json, 'timestamp'),
            _stringField(json, 'created_at'),
            '刚刚',
          ]),
          msgType: _stringField(json, 'msg_type').ifEmpty('text'),
        ),
      )
      .where((message) => message.body.trim().isNotEmpty)
      .toList(growable: false);
}

CsMessageResponse _parseCsMessageResponse(Object? value) {
  final data = _objectMap(value);
  return CsMessageResponse(
    messageId: _stringField(data, 'message_id'),
    requestId: _intField(data, 'request_id'),
    reply: _stringField(data, 'reply'),
    backend: _stringField(data, 'backend'),
    timestamp: _firstNonBlank([
      _stringField(data, 'timestamp'),
      _stringField(data, 'created_at'),
      '刚刚',
    ]),
  );
}

List<AdminCsInboxItem> _parseAdminCsInbox(Object? value) {
  final data = _objectMap(value);
  final raw = data['conversations'] ?? data['items'] ?? data['data'] ?? value;
  return _objectList(raw)
      .map(
        (json) => AdminCsInboxItem(
          conversationId: _intField(json, 'conversationId').ifZero(
            _intField(json, 'conversation_id').ifZero(_intField(json, 'id')),
          ),
          customerName: _firstNonBlank([
            _stringField(json, 'customerName'),
            _stringField(json, 'customer_name'),
            _stringField(json, 'name'),
            '客户',
          ]),
          lastMessageAt: _firstNonBlank([
            _stringField(json, 'lastMessageAt'),
            _stringField(json, 'last_message_at'),
            _stringField(json, 'updated_at'),
            _stringField(json, 'created_at'),
          ]),
          unreadCount: _intField(
            json,
            'unreadCount',
          ).ifZero(_intField(json, 'unread_count')),
        ),
      )
      .where((item) => item.conversationId > 0)
      .toList(growable: false);
}

List<AdminCsMessage> _parseAdminCsMessages(Object? value) {
  final data = _objectMap(value);
  final raw = data['messages'] ?? data['items'] ?? data['data'] ?? value;
  return _objectList(raw)
      .map(
        (json) => AdminCsMessage(
          messageId: _firstNonBlank([
            _stringField(json, 'messageId'),
            _stringField(json, 'message_id'),
            _stringField(json, 'id'),
          ]),
          fromCustomer: _boolField(json, 'fromCustomer') ||
              _boolField(json, 'from_customer'),
          senderName: _firstNonBlank([
            _stringField(json, 'senderName'),
            _stringField(json, 'sender_name'),
            _stringField(json, 'sender'),
          ]),
          body: _firstNonBlank([
            _stringField(json, 'body'),
            _stringField(json, 'content'),
            _stringField(json, 'text'),
          ]),
          timestamp: _firstNonBlank([
            _stringField(json, 'timestamp'),
            _stringField(json, 'created_at'),
            _stringField(json, 'updated_at'),
          ]),
        ),
      )
      .where((message) => message.body.trim().isNotEmpty)
      .toList(growable: false);
}

bool _shouldDispatchGroupTask(String text) {
  final body = text.trim();
  if (body.isEmpty) return false;
  const keywords = [
    '派工',
    '任务',
    '修复',
    'bug',
    '部署',
    '发布',
    '验收',
    '回访',
    '检查',
    '测试',
    '执行',
    '处理',
  ];
  return keywords.any((keyword) => body.contains(keyword));
}

Map<String, Object?> _objectMap(Object? value) {
  if (value is Map<String, Object?>) return value;
  if (value is Map) {
    return value.map((key, value) => MapEntry(key.toString(), value));
  }
  return const <String, Object?>{};
}

List<Map<String, Object?>> _objectList(Object? value) {
  if (value is List) {
    return value.map(_objectMap).where((item) => item.isNotEmpty).toList();
  }
  return const <Map<String, Object?>>[];
}

List<Map<String, Object?>> _firstObjectList(List<Object?> values) {
  for (final value in values) {
    final rows = _objectList(value);
    if (rows.isNotEmpty) return rows;
  }
  return const <Map<String, Object?>>[];
}

List<String> _stringList(Object? value) {
  if (value is List) {
    return value
        .map((item) => item?.toString().trim() ?? '')
        .where((item) => item.isNotEmpty)
        .toList(growable: false);
  }
  return const <String>[];
}

Map<String, Object?> _nestedDataMap(Map<String, Object?> data) {
  final nested = _objectMap(data['data']);
  return nested.isNotEmpty ? nested : data;
}

List<BusinessListItem> _businessItemsFromData(Map<String, Object?>? body) {
  final data = _nestedDataMap(body ?? const <String, Object?>{});
  final rows = _firstObjectList([data['items'], data['results'], data['data']]);
  return rows
      .map(BusinessListItem.fromJson)
      .where((item) => item.title.trim().isNotEmpty)
      .toList(growable: false);
}

List<BusinessListItem> _bridgeItemsFromData(Map<String, Object?>? body) {
  final data = _nestedDataMap(body ?? const <String, Object?>{});
  final rows = _firstObjectList([
    data['items'],
    data['requests'],
    data['results'],
    data['data'],
  ]);
  return rows
      .map(BusinessListItem.fromJson)
      .where(
        (item) => item.id.trim().isNotEmpty || item.title.trim().isNotEmpty,
      )
      .toList(growable: false);
}

OnboardingIndustry? _onboardingIndustryFromPackage(Map<String, Object?> json) {
  final industryId = _stringField(json, 'industry_id');
  if (industryId.isEmpty) return null;
  return OnboardingIndustry(
    id: industryId,
    title: _firstNonBlank([
      _stringField(json, 'name'),
      _stringField(json, 'product_name'),
      industryId,
    ]),
    subtitle: _firstNonBlank([
      _stringField(json, 'scenario'),
      _stringField(json, 'mod_id'),
    ]),
  );
}

String _stringField(Map<String, Object?> json, String key) {
  final value = json[key];
  if (value == null) return '';
  return value.toString().trim();
}

String? _nullableStringField(Map<String, Object?> json, String key) {
  final value = _stringField(json, key);
  return value.isEmpty ? null : value;
}
