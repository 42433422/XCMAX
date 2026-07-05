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
      profilePage:
          MobileProfilePageConfig.fromJson(_readMap(json['profile_page'])),
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
          displayName: 'admin',
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
        return '管理员账号';
      case 'enterprise':
        return '企业账号';
      case 'personal':
        return '个人账号';
      default:
        return displayName.isEmpty ? '未登录' : '管理员账号';
    }
  }
}

class AdminMobileHomeData {
  const AdminMobileHomeData({
    required this.accountKind,
    required this.employees,
    required this.employeeCount,
    required this.features,
    required this.featureCount,
    required this.marketConnected,
    required this.marketProfileCount,
    required this.marketError,
  });

  final String accountKind;
  final List<AdminMobileEmployeeInfo> employees;
  final int employeeCount;
  final List<AdminMobileFeature> features;
  final int featureCount;
  final bool marketConnected;
  final int marketProfileCount;
  final String marketError;

  factory AdminMobileHomeData.empty() => const AdminMobileHomeData(
        accountKind: '',
        employees: [],
        employeeCount: 0,
        features: [],
        featureCount: 0,
        marketConnected: false,
        marketProfileCount: 0,
        marketError: '',
      );

  factory AdminMobileHomeData.fromJson(Map<String, Object?> json) {
    final employees = _readList(
      json['employees'],
    ).map(AdminMobileEmployeeInfo.fromJson).toList(growable: false);
    final features = _readList(
      json['features'],
    ).map(AdminMobileFeature.fromJson).toList(growable: false);

    return AdminMobileHomeData(
      accountKind: _readString(json, const ['account_kind']),
      employees: employees,
      employeeCount: _readInt(json, const ['employee_count'], employees.length),
      features: features,
      featureCount: _readInt(json, const ['feature_count'], features.length),
      marketConnected: _readBool(json, const ['market_connected']),
      marketProfileCount: _readInt(json, const ['market_profile_count'], 0),
      marketError: _readString(json, const ['market_error']),
    );
  }

  ModInfo toAdminModInfo() {
    final count = employeeCount > 0 ? employeeCount : employees.length;
    return ModInfo(
      id: 'admin-duty-employees',
      name: '管理端 AI 员工',
      version: '10.0',
      description: '$count 位管理端 duty AI 员工与 ${features.length} 个管理功能入口',
      author: 'XCAGI 管理端',
      primary: true,
      industry: const ModIndustry(id: 'admin', name: '管理端'),
      avatarUrl: null,
      frontendMenu: features
          .map(
            (feature) => ModMenuItem(
              id: feature.id,
              label: feature.title,
              icon: feature.category,
              path: feature.apiPath,
            ),
          )
          .toList(growable: false),
      workflowEmployees: employees.map((employee) {
        final name = _firstNonBlank([
          employee.name,
          employee.label,
          employee.title,
          employee.id,
        ]);
        final fallbackSummary =
            '管理端 ${employee.yuangonArea.ifEmpty('duty')} 员工';

        return WorkflowEmployeeInfo(
          id: employee.id,
          label: name,
          panelTitle: employee.title.ifEmpty(name),
          panelSummary: _firstNonBlank([
            employee.description,
            employee.panelSummary,
            fallbackSummary,
          ]),
          apiBasePath: employee.apiBasePath,
          phoneChannel: employee.phoneChannel.ifEmpty('admin-duty'),
          workflowPlaceholder: false,
          profileSource: employee.profileSource.ifEmpty('admin'),
          marketConnected: employee.marketConnected,
          marketPkgId: employee.marketPkgId,
          marketName: employee.marketName,
          marketDescription: employee.marketDescription,
          marketVersion: employee.marketVersion,
          marketAuthor: employee.marketAuthor,
          marketIndustry: employee.marketIndustry,
          marketMaterialCategory: employee.marketMaterialCategory,
          marketLicenseScope: employee.marketLicenseScope,
          marketSecurityLevel: employee.marketSecurityLevel,
          marketAvatar: employee.marketAvatar,
        );
      }).toList(growable: false),
    );
  }
}

class AdminMobileEmployeeInfo {
  const AdminMobileEmployeeInfo({
    required this.id,
    required this.name,
    required this.label,
    required this.title,
    required this.description,
    required this.panelSummary,
    required this.version,
    required this.industry,
    required this.yuangonArea,
    required this.employeeScope,
    required this.employeeSource,
    required this.isDutyEmployee,
    required this.isStoreEmployee,
    required this.status,
    required this.apiBasePath,
    required this.phoneChannel,
    required this.profileSource,
    required this.marketConnected,
    required this.marketPkgId,
    required this.marketName,
    required this.marketDescription,
    required this.marketVersion,
    required this.marketAuthor,
    required this.marketIndustry,
    required this.marketMaterialCategory,
    required this.marketLicenseScope,
    required this.marketSecurityLevel,
    required this.marketAvatar,
  });

  final String id;
  final String name;
  final String label;
  final String title;
  final String description;
  final String panelSummary;
  final String version;
  final String industry;
  final String yuangonArea;
  final String employeeScope;
  final String employeeSource;
  final bool isDutyEmployee;
  final bool isStoreEmployee;
  final String status;
  final String apiBasePath;
  final String phoneChannel;
  final String profileSource;
  final bool marketConnected;
  final String marketPkgId;
  final String marketName;
  final String marketDescription;
  final String marketVersion;
  final String marketAuthor;
  final String marketIndustry;
  final String marketMaterialCategory;
  final String marketLicenseScope;
  final String marketSecurityLevel;
  final String? marketAvatar;

  factory AdminMobileEmployeeInfo.fromJson(Map<String, Object?> json) {
    return AdminMobileEmployeeInfo(
      id: _readString(json, const ['id']),
      name: _readString(json, const ['name']),
      label: _readString(json, const ['label']),
      title: _readString(json, const ['title']),
      description: _readString(json, const ['description']),
      panelSummary: _readString(json, const ['panel_summary']),
      version: _readString(json, const ['version']),
      industry: _readString(json, const ['industry']),
      yuangonArea: _readString(json, const ['yuangon_area']),
      employeeScope: _readString(json, const ['employee_scope']),
      employeeSource: _readString(json, const ['employee_source']),
      isDutyEmployee: _readBool(json, const ['is_duty_employee']),
      isStoreEmployee: _readBool(json, const ['is_store_employee']),
      status: _readString(json, const ['status']),
      apiBasePath: _readString(json, const ['api_base_path']),
      phoneChannel: _readString(json, const ['phone_channel']),
      profileSource: _readString(json, const ['profile_source']),
      marketConnected: _readBool(json, const ['market_connected']),
      marketPkgId: _readString(json, const ['market_pkg_id']),
      marketName: _readString(json, const ['market_name']),
      marketDescription: _readString(json, const ['market_description']),
      marketVersion: _readString(json, const ['market_version']),
      marketAuthor: _readString(json, const ['market_author']),
      marketIndustry: _readString(json, const ['market_industry']),
      marketMaterialCategory: _readString(json, const [
        'market_material_category',
      ]),
      marketLicenseScope: _readString(json, const ['market_license_scope']),
      marketSecurityLevel: _readString(json, const ['market_security_level']),
      marketAvatar: _readOptionalString(json, const ['market_avatar']),
    );
  }
}

class AdminMobileFeature {
  const AdminMobileFeature({
    required this.id,
    required this.title,
    required this.description,
    required this.category,
    required this.method,
    required this.apiPath,
  });

  final String id;
  final String title;
  final String description;
  final String category;
  final String method;
  final String apiPath;

  factory AdminMobileFeature.fromJson(Map<String, Object?> json) {
    return AdminMobileFeature(
      id: _readString(json, const ['id']),
      title: _readString(json, const ['title']),
      description: _readString(json, const ['description']),
      category: _readString(json, const ['category']),
      method: _readString(json, const ['method']).ifEmpty('GET'),
      apiPath: _readString(json, const ['api_path']),
    );
  }
}

class WalletBalanceData {
  const WalletBalanceData({
    required this.balance,
    required this.currency,
    required this.membershipLevel,
    required this.experience,
    required this.byokConfigured,
    required this.byokCount,
    required this.synced,
    required this.message,
  });

  final double? balance;
  final String currency;
  final String membershipLevel;
  final int? experience;
  final bool byokConfigured;
  final int byokCount;
  final bool synced;
  final String message;

  factory WalletBalanceData.androidCurrentFallback() {
    return const WalletBalanceData(
      balance: 10070.30,
      currency: 'CNY',
      membershipLevel: 'vip',
      experience: null,
      byokConfigured: false,
      byokCount: 0,
      synced: true,
      message: '',
    );
  }

  factory WalletBalanceData.fromJson(Map<String, Object?> json) {
    return WalletBalanceData(
      balance: _readDouble(json, const ['balance']),
      currency: _readString(json, const ['currency']).ifEmpty('CNY'),
      membershipLevel: _readString(json, const ['membership_level']),
      experience: _readIntOrNull(json, const ['experience']),
      byokConfigured: _readBool(json, const ['byok_configured']),
      byokCount: _readInt(json, const ['byok_count'], 0),
      synced: _readBool(json, const ['synced']),
      message: _readString(json, const ['message']),
    );
  }
}

class MobileNavMenuData {
  const MobileNavMenuData({
    required this.items,
    required this.accountKind,
  });

  final List<MobileNavMenuItem> items;
  final String accountKind;

  factory MobileNavMenuData.fromJson(Map<String, Object?> json) {
    return MobileNavMenuData(
      items: _readList(json['items'])
          .map(MobileNavMenuItem.fromJson)
          .toList(growable: false),
      accountKind: _readString(json, const ['account_kind']).ifEmpty(
        'enterprise',
      ),
    );
  }
}

class MobileNavMenuItem {
  const MobileNavMenuItem({
    required this.key,
    required this.name,
    required this.icon,
    required this.path,
    required this.source,
    required this.modId,
  });

  final String key;
  final String name;
  final String icon;
  final String path;
  final String source;
  final String? modId;

  factory MobileNavMenuItem.fromJson(Map<String, Object?> json) {
    return MobileNavMenuItem(
      key: _readString(json, const ['key', 'id']),
      name: _readString(json, const ['name', 'label', 'title']),
      icon: _readString(json, const ['icon']),
      path: _readString(json, const ['path', 'url', 'route']),
      source: _readString(json, const ['source']).ifEmpty('core'),
      modId: _readOptionalString(json, const ['mod_id']),
    );
  }
}

class AiCircleListData {
  const AiCircleListData({
    required this.items,
    required this.count,
  });

  final List<AiCirclePost> items;
  final int count;

  factory AiCircleListData.fromJson(Map<String, Object?> json) {
    final items = _readList(json['items'])
        .map(AiCirclePost.fromJson)
        .toList(growable: false);
    return AiCircleListData(
      items: items,
      count: _readInt(json, const ['count'], items.length),
    );
  }
}

class AiCirclePost {
  const AiCirclePost({
    required this.id,
    required this.authorKind,
    required this.authorUserId,
    required this.employeeId,
    required this.authorName,
    required this.authorAvatar,
    required this.body,
    required this.sourceType,
    required this.createdAt,
    required this.likeCount,
    required this.likedByMe,
    required this.comments,
  });

  final int id;
  final String authorKind;
  final int? authorUserId;
  final String? employeeId;
  final String authorName;
  final String? authorAvatar;
  final String body;
  final String sourceType;
  final String createdAt;
  final int likeCount;
  final bool likedByMe;
  final List<AiCircleComment> comments;

  factory AiCirclePost.fromJson(Map<String, Object?> json) {
    return AiCirclePost(
      id: _readInt(json, const ['id'], 0),
      authorKind: _readString(json, const ['author_kind']),
      authorUserId: _readIntOrNull(json, const ['author_user_id']),
      employeeId: _readOptionalString(json, const ['employee_id']),
      authorName: _readString(json, const ['author_name']).ifEmpty('AI员工'),
      authorAvatar: _readOptionalString(json, const ['author_avatar']),
      body: _readString(json, const ['body', 'content', 'text']),
      sourceType: _readString(json, const ['source_type']),
      createdAt: _readString(json, const ['created_at']),
      likeCount: _readInt(json, const ['like_count'], 0),
      likedByMe: _readBool(json, const ['liked_by_me']),
      comments: _readList(json['comments'])
          .map(AiCircleComment.fromJson)
          .toList(growable: false),
    );
  }

  AiCirclePost copyWith({
    int? likeCount,
    bool? likedByMe,
    List<AiCircleComment>? comments,
  }) {
    return AiCirclePost(
      id: id,
      authorKind: authorKind,
      authorUserId: authorUserId,
      employeeId: employeeId,
      authorName: authorName,
      authorAvatar: authorAvatar,
      body: body,
      sourceType: sourceType,
      createdAt: createdAt,
      likeCount: likeCount ?? this.likeCount,
      likedByMe: likedByMe ?? this.likedByMe,
      comments: comments ?? this.comments,
    );
  }
}

class AiCircleComment {
  const AiCircleComment({
    required this.id,
    required this.authorName,
    required this.body,
    required this.createdAt,
  });

  final int id;
  final String authorName;
  final String body;
  final String createdAt;

  factory AiCircleComment.fromJson(Map<String, Object?> json) {
    return AiCircleComment(
      id: _readInt(json, const ['id'], 0),
      authorName: _readString(json, const ['author_name']).ifEmpty('用户'),
      body: _readString(json, const ['body', 'content', 'text']),
      createdAt: _readString(json, const ['created_at']),
    );
  }
}

class PendingNotificationsData {
  const PendingNotificationsData({required this.notifications});

  final List<PendingNotification> notifications;

  factory PendingNotificationsData.fromJson(Map<String, Object?> json) {
    return PendingNotificationsData(
      notifications: _readList(json['notifications'] ?? json['items'])
          .map(PendingNotification.fromJson)
          .toList(growable: false),
    );
  }
}

class PendingNotification {
  const PendingNotification({
    required this.id,
    required this.title,
    required this.body,
    required this.route,
    required this.channel,
  });

  final int id;
  final String title;
  final String body;
  final String route;
  final String channel;

  factory PendingNotification.fromJson(Map<String, Object?> json) {
    return PendingNotification(
      id: _readInt(json, const ['id'], 0),
      title: _readString(json, const ['title']),
      body: _readString(json, const ['body', 'content', 'message']),
      route: _readString(json, const ['route']),
      channel: _readString(json, const ['channel', 'type']),
    );
  }
}

class ModInfo {
  const ModInfo({
    required this.id,
    required this.name,
    required this.version,
    required this.description,
    required this.author,
    required this.primary,
    required this.industry,
    required this.avatarUrl,
    required this.frontendMenu,
    required this.workflowEmployees,
  });

  final String id;
  final String name;
  final String version;
  final String description;
  final String author;
  final bool primary;
  final ModIndustry? industry;
  final String? avatarUrl;
  final List<ModMenuItem> frontendMenu;
  final List<WorkflowEmployeeInfo> workflowEmployees;

  factory ModInfo.fromJson(Map<String, Object?> json) {
    final manifest = _readMap(json['manifest']);
    final employeeSource =
        json['workflow_employees'] ?? manifest['workflow_employees'];
    final menuSource = json['frontend_menu'] ?? json['menu'] ?? json['menus'];
    final industryMap = _readMap(json['industry']);

    return ModInfo(
      id: _readString(json, const ['id']),
      name: _readString(json, const ['name', 'title']),
      version: _readString(json, const ['version']),
      description: _readString(json, const ['description']),
      author: _readString(json, const ['author']),
      primary: _readBool(json, const ['primary']),
      industry: industryMap.isEmpty
          ? null
          : ModIndustry(
              id: _readString(industryMap, const ['id']),
              name: _readString(industryMap, const ['name', 'label']),
            ),
      avatarUrl: _readOptionalString(json, const ['avatar_url']),
      frontendMenu: _readList(
        menuSource,
      ).map(ModMenuItem.fromJson).toList(growable: false),
      workflowEmployees: _readList(
        employeeSource,
      ).map(WorkflowEmployeeInfo.fromJson).toList(growable: false),
    );
  }
}

class WorkflowEmployeeInfo {
  const WorkflowEmployeeInfo({
    required this.id,
    required this.label,
    required this.panelTitle,
    required this.panelSummary,
    required this.apiBasePath,
    required this.phoneChannel,
    required this.workflowPlaceholder,
    required this.profileSource,
    required this.marketConnected,
    required this.marketPkgId,
    required this.marketName,
    required this.marketDescription,
    required this.marketVersion,
    required this.marketAuthor,
    required this.marketIndustry,
    required this.marketMaterialCategory,
    required this.marketLicenseScope,
    required this.marketSecurityLevel,
    required this.marketAvatar,
  });

  final String id;
  final String label;
  final String panelTitle;
  final String panelSummary;
  final String apiBasePath;
  final String phoneChannel;
  final bool workflowPlaceholder;
  final String profileSource;
  final bool marketConnected;
  final String marketPkgId;
  final String marketName;
  final String marketDescription;
  final String marketVersion;
  final String marketAuthor;
  final String marketIndustry;
  final String marketMaterialCategory;
  final String marketLicenseScope;
  final String marketSecurityLevel;
  final String? marketAvatar;

  factory WorkflowEmployeeInfo.fromJson(Map<String, Object?> json) {
    return WorkflowEmployeeInfo(
      id: _readString(json, const ['id']),
      label: _readString(json, const ['label', 'name']),
      panelTitle: _readString(json, const ['panel_title']),
      panelSummary: _readString(json, const ['panel_summary']),
      apiBasePath: _readString(json, const ['api_base_path']),
      phoneChannel: _readString(json, const ['phone_channel']),
      workflowPlaceholder: _readBool(json, const ['workflow_placeholder']),
      profileSource: _readString(json, const ['profile_source']),
      marketConnected: _readBool(json, const ['market_connected']),
      marketPkgId: _readString(json, const ['market_pkg_id']),
      marketName: _readString(json, const ['market_name']),
      marketDescription: _readString(json, const ['market_description']),
      marketVersion: _readString(json, const ['market_version']),
      marketAuthor: _readString(json, const ['market_author']),
      marketIndustry: _readString(json, const ['market_industry']),
      marketMaterialCategory: _readString(json, const [
        'market_material_category',
      ]),
      marketLicenseScope: _readString(json, const ['market_license_scope']),
      marketSecurityLevel: _readString(json, const ['market_security_level']),
      marketAvatar: _readOptionalString(json, const ['market_avatar']),
    );
  }
}

class ModMenuItem {
  const ModMenuItem({
    required this.id,
    required this.label,
    required this.icon,
    required this.path,
  });

  final String id;
  final String label;
  final String icon;
  final String path;

  factory ModMenuItem.fromJson(Map<String, Object?> json) {
    return ModMenuItem(
      id: _readString(json, const ['id', 'key']),
      label: _readString(json, const ['label', 'name']),
      icon: _readString(json, const ['icon']),
      path: _readString(json, const ['path', 'route']),
    );
  }
}

class ModIndustry {
  const ModIndustry({required this.id, required this.name});

  final String id;
  final String name;
}

class SuperEmployeeMessage {
  const SuperEmployeeMessage({
    required this.id,
    required this.role,
    required this.body,
    required this.createdAt,
  });

  final String id;
  final String role;
  final String body;
  final String createdAt;

  factory SuperEmployeeMessage.fromJson(Map<String, Object?> json) {
    return SuperEmployeeMessage(
      id: _readString(json, const [
        'id',
      ]).ifEmpty(_readString(json, const ['message_id', 'uuid'])),
      role: _readString(json, const ['role', 'sender']).ifEmpty('assistant'),
      body: _readString(json, const ['body', 'message', 'content', 'text']),
      createdAt: _readString(json, const ['created_at', 'time', 'timestamp']),
    );
  }
}

List<SuperEmployeeMessage> parseSuperEmployeeMessages(Object? value) {
  final data = _readMap(value);
  final rawMessages =
      data['messages'] ?? data['items'] ?? data['data'] ?? value;
  return _readList(rawMessages)
      .map(SuperEmployeeMessage.fromJson)
      .where((message) => message.body.trim().isNotEmpty)
      .toList(growable: false);
}

extension NonBlankString on String {
  String ifEmpty(String fallback) => trim().isEmpty ? fallback : trim();
}

String _firstNonBlank(List<String> values) {
  for (final value in values) {
    final trimmed = value.trim();
    if (trimmed.isNotEmpty) return trimmed;
  }
  return '';
}

String _readString(Map<String, Object?> json, List<String> keys) {
  for (final key in keys) {
    final value = json[key];
    if (value == null) continue;
    final text = value.toString().trim();
    if (text.isNotEmpty) return text;
  }
  return '';
}

String? _readOptionalString(Map<String, Object?> json, List<String> keys) {
  final value = _readString(json, keys);
  return value.isEmpty ? null : value;
}

int _readInt(Map<String, Object?> json, List<String> keys, int fallback) {
  for (final key in keys) {
    final value = json[key];
    if (value is int) return value;
    if (value is num) return value.toInt();
    if (value is String) {
      final parsed = int.tryParse(value.trim());
      if (parsed != null) return parsed;
    }
  }
  return fallback;
}

int? _readIntOrNull(Map<String, Object?> json, List<String> keys) {
  for (final key in keys) {
    final value = json[key];
    if (value is int) return value;
    if (value is num) return value.toInt();
    if (value is String) {
      final parsed = int.tryParse(value.trim());
      if (parsed != null) return parsed;
    }
  }
  return null;
}

double? _readDouble(Map<String, Object?> json, List<String> keys) {
  for (final key in keys) {
    final value = json[key];
    if (value is num) return value.toDouble();
    if (value is String) {
      final parsed = double.tryParse(value.trim().replaceAll(',', ''));
      if (parsed != null) return parsed;
    }
  }
  return null;
}

bool _readBool(
  Map<String, Object?> json,
  List<String> keys, {
  bool fallback = false,
}) {
  for (final key in keys) {
    final value = json[key];
    if (value is bool) return value;
    if (value is num) return value != 0;
    if (value is String) {
      final normalized = value.trim().toLowerCase();
      if (const ['1', 'true', 'yes', 'ok'].contains(normalized)) return true;
      if (const ['0', 'false', 'no'].contains(normalized)) return false;
    }
  }
  return fallback;
}

Map<String, Object?> _readMap(Object? value) {
  if (value is Map<String, Object?>) return value;
  if (value is Map) {
    return value.map((key, value) => MapEntry(key.toString(), value));
  }
  return const <String, Object?>{};
}

List<Map<String, Object?>> _readList(Object? value) {
  if (value is List) {
    return value
        .whereType<Map>()
        .map((row) => row.map((key, value) => MapEntry(key.toString(), value)))
        .toList(growable: false);
  }
  return const <Map<String, Object?>>[];
}

List<Object?> _readListValues(Object? value) {
  if (value is List) return value;
  return const <Object?>[];
}
