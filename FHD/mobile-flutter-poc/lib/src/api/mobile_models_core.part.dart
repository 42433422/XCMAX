// part 文件：信封与配置、用户资料模型。

part of 'mobile_models.dart';

class MobileEnvelope<T> {
  const MobileEnvelope({
    required this.success,
    required this.message,
    required this.data,
    required this.raw,
  });

  final bool success;
  final String message;
  final T? data;
  final Map<String, Object?> raw;

  factory MobileEnvelope.fromJson(
    Map<String, Object?> json,
    T Function(Object? value) decodeData,
  ) {
    return MobileEnvelope<T>(
      success: _readBool(json, const ['success', 'ok'], fallback: true),
      message: _readString(json, const ['message', 'error']),
      data: json.containsKey('data') ? decodeData(json['data']) : null,
      raw: json,
    );
  }
}

class MobileTaskSummary {
  const MobileTaskSummary({
    required this.taskId,
    required this.title,
    required this.status,
    required this.attentionState,
    required this.approvalRequired,
    required this.executionTarget,
    required this.progressPercent,
    required this.workspaceId,
    required this.conversationId,
    required this.updatedAt,
  });

  final String taskId;
  final String title;
  final String status;
  final String attentionState;
  final bool approvalRequired;
  final String executionTarget;
  final int progressPercent;
  final String workspaceId;
  final String conversationId;
  final String updatedAt;

  factory MobileTaskSummary.fromJson(Map<String, Object?> json) {
    return MobileTaskSummary(
      taskId: _readString(json, const ['task_id']),
      title: _readString(json, const ['title']),
      status: _readString(json, const ['status']),
      attentionState: _readString(json, const ['attention_state']),
      approvalRequired: _readBool(json, const ['approval_required']),
      executionTarget: _readString(json, const ['execution_target']),
      progressPercent: _readInt(json, const ['progress_percent'], 0),
      workspaceId: _readString(json, const ['workspace_id']),
      conversationId: _readString(json, const ['conversation_id']),
      updatedAt: _readString(json, const ['updated_at']),
    );
  }
}

class MobileTaskListData {
  const MobileTaskListData({required this.items, required this.count});

  final List<MobileTaskSummary> items;
  final int count;

  factory MobileTaskListData.fromJson(Map<String, Object?> json) {
    final rawItems = json['items'];
    final items = rawItems is List
        ? rawItems
            .whereType<Map>()
            .map(
              (item) => MobileTaskSummary.fromJson(
                Map<String, Object?>.from(item),
              ),
            )
            .toList(growable: false)
        : const <MobileTaskSummary>[];
    return MobileTaskListData(
      items: items,
      count: _readInt(json, const ['count'], items.length).clamp(0, items.length),
    );
  }
}

class MobileAppConfigData {
  const MobileAppConfigData({
    required this.ok,
    required this.legalVersion,
    this.sku = '',
    required this.profilePage,
    required this.raw,
  });

  final bool ok;
  final String legalVersion;
  final String sku;
  final MobileProfilePageConfig profilePage;
  final Map<String, Object?> raw;

  factory MobileAppConfigData.empty() => const MobileAppConfigData(
        ok: false,
        legalVersion: '1',
        sku: '',
        profilePage: MobileProfilePageConfig.disabled(),
        raw: {},
      );

  factory MobileAppConfigData.fromJson(Map<String, Object?> json) {
    return MobileAppConfigData(
      ok: _readBool(json, const ['ok', 'success']),
      legalVersion: _readString(json, const ['legal_version']).ifEmpty('1'),
      sku: _readString(json, const ['sku']),
      profilePage: MobileProfilePageConfig.fromJson(
        _readMap(json['profile_page']),
      ),
      raw: json,
    );
  }
}

class MobileProfilePageConfig {
  const MobileProfilePageConfig({
    required this.enabled,
    required this.revision,
    required this.heroVariant,
    required this.headline,
    required this.subtitle,
    required this.statusReady,
    required this.statusSyncing,
    required this.primaryChip,
    required this.secondaryChip,
    required this.accent,
  });

  const MobileProfilePageConfig.disabled()
      : enabled = false,
        revision = '',
        heroVariant = 'glass',
        headline = '',
        subtitle = '',
        statusReady = '',
        statusSyncing = '',
        primaryChip = '',
        secondaryChip = '',
        accent = 'indigo';

  final bool enabled;
  final String revision;
  final String heroVariant;
  final String headline;
  final String subtitle;
  final String statusReady;
  final String statusSyncing;
  final String primaryChip;
  final String secondaryChip;
  final String accent;

  factory MobileProfilePageConfig.fromJson(Map<String, Object?> json) {
    return MobileProfilePageConfig(
      enabled: _readBool(json, const ['enabled']),
      revision: _readString(json, const ['revision']),
      heroVariant: _readString(json, const ['hero_variant']).ifEmpty('glass'),
      headline: _readString(json, const ['headline']),
      subtitle: _readString(json, const ['subtitle']),
      statusReady: _readString(json, const ['status_ready']),
      statusSyncing: _readString(json, const ['status_syncing']),
      primaryChip: _readString(json, const ['primary_chip']),
      secondaryChip: _readString(json, const ['secondary_chip']),
      accent: _readString(json, const ['accent']).ifEmpty('indigo'),
    );
  }
}

class MobileUserData {
  const MobileUserData({
    required this.id,
    required this.username,
    required this.displayName,
    required this.email,
    required this.role,
    required this.isActive,
    required this.avatarUrl,
  });

  final int id;
  final String username;
  final String displayName;
  final String email;
  final String role;
  final bool isActive;
  final String? avatarUrl;

  factory MobileUserData.fromJson(Map<String, Object?> json) {
    return MobileUserData(
      id: _readInt(json, const ['id'], 0),
      username: _readString(json, const ['username', 'name']),
      displayName: _readString(json, const ['display_name', 'displayName']),
      email: _readString(json, const ['email']),
      role: _readString(json, const ['role']),
      isActive: _readBool(json, const ['is_active'], fallback: true),
      avatarUrl: _readOptionalString(json, const ['avatar_url', 'avatar']),
    );
  }
}

class MobileMeData {
  const MobileMeData({
    required this.user,
    required this.permissions,
    required this.accountKind,
    required this.companyBrand,
    required this.modIds,
  });

  final MobileUserData? user;
  final List<String> permissions;
  final String accountKind;
  final String companyBrand;
  final List<String> modIds;

  factory MobileMeData.adminFallback({String avatarUrl = ''}) => MobileMeData(
        user: MobileUserData(
          id: 0,
          username: 'admin',
          displayName: 'XCAGI 企业版',
          email: '',
          role: 'admin',
          isActive: true,
          avatarUrl: avatarUrl.trim().isEmpty ? null : avatarUrl.trim(),
        ),
        permissions: const [],
        accountKind: 'admin',
        companyBrand: '',
        modIds: const [],
      );

  factory MobileMeData.fromJson(Map<String, Object?> json) {
    final userMap = _readMap(json['user']);
    return MobileMeData(
      user: userMap.isEmpty ? null : MobileUserData.fromJson(userMap),
      permissions: _readListValues(json['permissions'])
          .where((value) => value != null)
          .map((value) => '$value')
          .where((value) => value.trim().isNotEmpty)
          .toList(growable: false),
      accountKind: _readString(json, const ['account_kind']),
      companyBrand: _readString(json, const ['company_brand']),
      modIds: _readList(json['mods'])
          .map((mod) => _readString(mod, const ['id']))
          .where((id) => id.isNotEmpty)
          .toList(growable: false),
    );
  }

  String get displayName {
    return _firstNonBlank([
      user?.username ?? '',
      user?.displayName ?? '',
      companyBrand,
    ]);
  }

  String get avatarSource => user?.avatarUrl?.trim() ?? '';

  String get accountKindLabel {
    switch (accountKind.trim().toLowerCase()) {
      case 'admin':
      case 'admin_portal':
        return '账号';
      case 'enterprise':
        return '账号';
      case 'personal':
        return '个人账号';
      default:
        return displayName.isEmpty ? '未登录' : '账号';
    }
  }
}
