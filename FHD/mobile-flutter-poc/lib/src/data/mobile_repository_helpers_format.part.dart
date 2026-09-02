part of 'mobile_repository.dart';

String _formatCents(String cents) {
  final parsed = double.tryParse(cents.trim());
  if (parsed == null) return cents;
  return '¥${(parsed / 100).toStringAsFixed(2)}';
}

String _checkoutResultText(Map<String, Object?> json) {
  final data = _nestedDataMap(json);
  return _firstNonBlank([
    _stringField(data, 'payment_url'),
    _stringField(data, 'pay_url'),
    _stringField(data, 'checkout_url'),
    _stringField(data, 'h5_url'),
    _stringField(data, 'url'),
    _stringField(data, 'out_trade_no'),
    _stringField(data, 'message'),
    '订单已创建',
  ]);
}

int _intField(Map<String, Object?> json, String key) {
  final value = json[key];
  if (value is int) return value;
  if (value is num) return value.toInt();
  if (value is String) return int.tryParse(value.trim()) ?? 0;
  return 0;
}

bool _boolField(
  Map<String, Object?> json,
  String key, {
  bool fallback = false,
}) {
  final value = json[key];
  if (value is bool) return value;
  if (value is num) return value != 0;
  if (value is String) {
    final normalized = value.trim().toLowerCase();
    if (const ['1', 'true', 'yes', 'ok'].contains(normalized)) return true;
    if (const ['0', 'false', 'no'].contains(normalized)) return false;
  }
  return fallback;
}

String _ensureTrailingSlash(String value) {
  final clean = value.trim();
  if (clean.isEmpty) return '';
  return clean.endsWith('/') ? clean : '$clean/';
}

String _friendlyGroupTimestamp(String value) {
  final parsed = DateTime.tryParse(value.trim());
  if (parsed == null) return '';
  return _friendlyTimestampFromMillis(parsed.toLocal().millisecondsSinceEpoch);
}

String _friendlyTimestampFromMillis(int timestampMs) {
  if (timestampMs <= 0) return '';
  final local = DateTime.fromMillisecondsSinceEpoch(timestampMs);
  final now = DateTime.now();
  final diff = now.difference(local);
  if (diff.isNegative) return '刚刚';
  if (diff.inMinutes < 1) return '刚刚';
  if (diff.inHours < 1) return '${diff.inMinutes}分钟前';
  if (diff.inHours < 24) return '${diff.inHours}小时前';
  if (diff.inHours < 48) return '昨天';
  if (local.year != now.year) {
    final shortYear = (local.year % 100).toString().padLeft(2, '0');
    return '$shortYear/${local.month}/${local.day}';
  }
  return '${local.month}/${local.day}';
}

ModInfo _normalizeAdminDutyMod(ModInfo mod) {
  if (mod.id != adminDutyModId && mod.id != 'admin-duty') return mod;

  final remoteById = <String, WorkflowEmployeeInfo>{};
  for (final employee in mod.workflowEmployees) {
    final id = employee.id.trim();
    if (id.isEmpty || remoteById.containsKey(id)) continue;
    remoteById[id] = employee;
  }

  final employees = adminDutyRosterEmployees.map((fallback) {
    final remote = remoteById[fallback.id];
    final label = _adminDutyEmployeeLabel(fallback, remote);
    final apiBasePath = '/api/admin/employees/${fallback.id}';
    return WorkflowEmployeeInfo(
      id: fallback.id,
      label: label.ifEmpty(fallback.label),
      panelTitle: fallback.id == 'user-customer-service-officer'
          ? label
          : remote == null
              ? fallback.label
              : remote.panelTitle.ifEmpty(label),
      panelSummary: fallback.id == 'user-customer-service-officer'
          ? fallback.summary
          : remote == null
              ? fallback.summary
              : remote.panelSummary.ifEmpty(fallback.summary),
      apiBasePath: remote == null
          ? apiBasePath
          : remote.apiBasePath.ifEmpty(apiBasePath),
      phoneChannel: remote == null
          ? 'admin-duty'
          : remote.phoneChannel.ifEmpty('admin-duty'),
      workflowPlaceholder: false,
      profileSource: remote == null
          ? 'duty_roster'
          : remote.profileSource.ifEmpty('duty_roster'),
      marketConnected: remote?.marketConnected ?? false,
      marketPkgId: remote?.marketPkgId ?? '',
      marketName: remote?.marketName ?? '',
      marketDescription: remote?.marketDescription ?? '',
      marketVersion: remote?.marketVersion ?? '',
      marketAuthor: remote?.marketAuthor ?? '',
      marketIndustry: remote?.marketIndustry ?? '',
      marketMaterialCategory: remote?.marketMaterialCategory ?? '',
      marketLicenseScope: remote?.marketLicenseScope ?? '',
      marketSecurityLevel: remote?.marketSecurityLevel ?? '',
      marketAvatar: remote?.marketAvatar,
    );
  }).toList(growable: false);

  return ModInfo(
    id: adminDutyModId,
    name: mod.name,
    version: mod.version,
    description:
        '$plannedAdminEmployeeCount 位系统 AI 员工与 ${mod.frontendMenu.length} 个管理功能入口',
    author: mod.author,
    primary: mod.primary,
    industry: mod.industry,
    avatarUrl: mod.avatarUrl,
    frontendMenu: mod.frontendMenu,
    workflowEmployees: employees,
  );
}

String _adminDutyEmployeeLabel(
  DutyRosterEmployee fallback,
  WorkflowEmployeeInfo? remote,
) {
  if (fallback.id == 'user-customer-service-officer') {
    return fallback.label;
  }
  return remote == null
      ? fallback.label
      : remote.label.ifEmpty(remote.panelTitle).ifEmpty(fallback.label);
}

List<ConversationItem> _employeeConversationItems(
  List<ModInfo> mods, {
  required String? badgeText,
  required int? badgeColor,
  required Map<String, _ConversationListState> states,
}) {
  final seenIds = <String>{};
  final items = <ConversationItem>[];

  for (final mod in mods) {
    for (final employee in mod.workflowEmployees) {
      final employeeId = employee.id.trim();
      final title = employee.label
          .ifEmpty(employee.panelTitle)
          .ifEmpty(employeeId)
          .trim();
      if (employeeId.isEmpty || title.isEmpty) continue;

      final source = mod.name.ifEmpty(mod.id).trim();
      final conversationId = 'employee:${mod.id}:$employeeId';
      if (!seenIds.add(conversationId)) continue;
      final state = states[conversationId];

      items.add(
        ConversationItem(
          id: conversationId,
          type: ConversationType.aiTask,
          title: title,
          subtitle: state?.preview.ifEmpty(employee.contactSubtitle(source)) ??
              employee.contactSubtitle(source),
          timestampText: state?.timestampText ?? '',
          timestampMs: state?.timestampMs ?? 0,
          avatarUrl: employee.marketAvatar ?? mod.avatarUrl,
          badgeText: badgeText,
          badgeColor: badgeColor,
        ),
      );
    }
  }

  return items;
}

List<ConversationItem> _sortConversationItems(List<ConversationItem> items) {
  final entries = <_IndexedConversationItem>[
    for (var i = 0; i < items.length; i++)
      _IndexedConversationItem(index: i, item: items[i]),
  ];
  entries.sort((a, b) {
    if (a.item.isPinned != b.item.isPinned) {
      return a.item.isPinned ? -1 : 1;
    }
    final timestampOrder = b.item.timestampMs.compareTo(a.item.timestampMs);
    if (timestampOrder != 0) return timestampOrder;
    return a.index.compareTo(b.index);
  });
  return entries.map((entry) => entry.item).toList(growable: false);
}
