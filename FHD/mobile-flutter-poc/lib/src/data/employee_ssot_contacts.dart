import '../api/mobile_models.dart';
import '../models/conversation.dart';
import 'duty_roster_ssot.dart';

class EmployeeSsotContactRecord {
  const EmployeeSsotContactRecord({
    required this.employeeId,
    required this.displayName,
    required this.department,
    required this.source,
    required this.installed,
    required this.runnable,
    required this.description,
    required this.contactRoute,
    required this.mobileContactRoute,
    this.pinned = false,
  });

  final String employeeId;
  final String displayName;
  final String department;
  final String source;
  final bool installed;
  final bool runnable;
  final String description;
  final String contactRoute;
  final String mobileContactRoute;
  final bool pinned;

  factory EmployeeSsotContactRecord.fromJson(Map<String, Object?> json) {
    final employeeId = _stringField(json, 'employee_id');
    final source = _stringField(json, 'source');
    final installed = _boolField(json, 'installed');
    return EmployeeSsotContactRecord(
      employeeId: employeeId,
      displayName: _stringField(json, 'display_name').ifEmpty(employeeId),
      department: _stringField(json, 'department').ifEmpty('编制'),
      source: source.ifEmpty(installed ? 'installed' : 'planned'),
      installed: installed,
      runnable: _boolField(json, 'runnable', fallback: installed),
      description: _stringField(json, 'description'),
      contactRoute: _stringField(json, 'contact_route'),
      mobileContactRoute: _stringField(json, 'mobile_contact_route'),
      pinned: _boolField(json, 'pinned'),
    );
  }
}

List<EmployeeSsotContactRecord> employeeContactsFromSsotPayload(
  Map<String, Object?>? payload,
) {
  if (payload == null || payload.isEmpty) return const [];
  final raw = payload['contacts'];
  if (raw is! List) return const [];
  final out = <EmployeeSsotContactRecord>[];
  for (final item in raw) {
    if (item is! Map) continue;
    final record = EmployeeSsotContactRecord.fromJson(
      Map<String, Object?>.from(item),
    );
    if (record.employeeId.isEmpty) continue;
    out.add(record);
  }
  return out;
}

List<EmployeeSsotContactRecord> platformEmployeeContactsFromSsotPayload(
  Map<String, Object?>? payload,
) {
  return employeeContactsFromSsotPayload(payload).where((row) {
    final source = row.source.trim().toLowerCase();
    return source != 'builtin' && source != 'codex';
  }).toList(growable: false);
}

WorkflowEmployeeInfo workflowEmployeeFromSsotContact(
  EmployeeSsotContactRecord contact,
) {
  final apiBasePath = contact.contactRoute
      .replaceAll(RegExp(r'/chat/?$'), '')
      .replaceAll(RegExp(r'/messages/?$'), '')
      .ifEmpty('/api/admin/employees/${contact.employeeId}');
  final subtitle = contact.runnable
      ? '${contact.department} · 可执行'
      : contact.source == 'planned'
          ? '${contact.department} · 未安装'
          : '${contact.department} · ${contact.source}';
  return WorkflowEmployeeInfo(
    id: contact.employeeId,
    label: contact.displayName,
    panelTitle: contact.displayName,
    panelSummary: contact.description.ifEmpty(subtitle),
    apiBasePath: apiBasePath,
    phoneChannel: contact.source == 'builtin' || contact.source == 'codex'
        ? 'super'
        : 'admin-duty',
    workflowPlaceholder: false,
    profileSource: contact.source.ifEmpty('duty_roster'),
    marketConnected: false,
    marketPkgId: '',
    marketName: '',
    marketDescription: '',
    marketVersion: '',
    marketAuthor: '',
    marketIndustry: '',
    marketMaterialCategory: '',
    marketLicenseScope: '',
    marketSecurityLevel: '',
    marketAvatar: null,
  );
}

ModInfo adminDutyModFromSsotContacts(Map<String, Object?>? payload) {
  final contacts = platformEmployeeContactsFromSsotPayload(payload);
  final employees =
      contacts.map(workflowEmployeeFromSsotContact).toList(growable: false);
  if (employees.isEmpty) {
    return ModInfo(
      id: adminDutyModId,
      name: '管理端编制员工',
      version: 'local',
      description: '$plannedAdminEmployeeCount 位管理端编制 AI 员工',
      author: 'XCAGI 管理端',
      primary: true,
      industry: const ModIndustry(id: '管理端', name: '管理端'),
      avatarUrl: null,
      frontendMenu: const [],
      workflowEmployees: adminDutyRosterEmployees
          .map(
            (fallback) => WorkflowEmployeeInfo(
              id: fallback.id,
              label: fallback.label,
              panelTitle: fallback.label,
              panelSummary: fallback.summary,
              apiBasePath: '/api/admin/employees/${fallback.id}',
              phoneChannel: 'admin-duty',
              workflowPlaceholder: false,
              profileSource: 'duty_roster',
              marketConnected: false,
              marketPkgId: '',
              marketName: '',
              marketDescription: '',
              marketVersion: '',
              marketAuthor: '',
              marketIndustry: '',
              marketMaterialCategory: '',
              marketLicenseScope: '',
              marketSecurityLevel: '',
              marketAvatar: null,
            ),
          )
          .toList(growable: false),
    );
  }

  return ModInfo(
    id: adminDutyModId,
    name: '管理端编制员工',
    version: 'local',
    description: '${employees.length} 位管理端编制 AI 员工，来自 employee-ssot。',
    author: 'XCAGI 管理端',
    primary: true,
    industry: const ModIndustry(id: '管理端', name: '管理端'),
    avatarUrl: null,
    frontendMenu: const [],
    workflowEmployees: employees,
  );
}

List<ConversationItem> adminDutyConversationItemsFromSsotPayload(
  Map<String, Object?>? payload,
) {
  final contacts = platformEmployeeContactsFromSsotPayload(payload);
  if (contacts.isEmpty) return adminDutyRosterConversationItems();
  return contacts
      .map(
        (contact) => ConversationItem(
          id: 'employee:$adminDutyModId:${contact.employeeId}',
          type: ConversationType.aiTask,
          title: contact.displayName,
          subtitle: contact.description.ifEmpty(
            contact.runnable
                ? '${contact.department} · 可执行'
                : '${contact.department} · 未安装',
          ),
          timestampText: '',
          badgeText: contact.runnable ? null : '未安装',
        ),
      )
      .toList(growable: false);
}

String _stringField(Map<String, Object?> json, String key) {
  final value = json[key];
  return value == null ? '' : value.toString().trim();
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
    if (normalized == 'true' || normalized == '1') return true;
    if (normalized == 'false' || normalized == '0') return false;
  }
  return fallback;
}
