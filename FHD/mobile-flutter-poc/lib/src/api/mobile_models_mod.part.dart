// part 文件：通知与 Mod/员工工作流模型。

part of 'mobile_models.dart';

class PendingNotificationsData {
  const PendingNotificationsData({required this.notifications});

  final List<PendingNotification> notifications;

  factory PendingNotificationsData.fromJson(Map<String, Object?> json) {
    return PendingNotificationsData(
      notifications: _readList(
        json['notifications'] ?? json['items'],
      ).map(PendingNotification.fromJson).toList(growable: false),
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
