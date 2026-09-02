// part 文件：管理端首页模型。

part of 'mobile_models.dart';

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
      name: '系统 AI 员工',
      version: '10.0',
      description: '$count 位系统 AI 员工与 ${features.length} 个管理功能入口',
      author: 'XCAGI',
      primary: true,
      industry: const ModIndustry(id: 'admin', name: '服务器后台'),
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
            '服务器后台 ${employee.yuangonArea.ifEmpty('duty')} 员工';

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
