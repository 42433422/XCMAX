import '../api/mobile_models.dart';
import 'duty_roster_ssot.dart';

class AiEmployeeProfile {
  const AiEmployeeProfile({
    required this.modId,
    required this.modName,
    required this.modDescription,
    required this.modVersion,
    required this.modAuthor,
    required this.industryName,
    required this.employeeId,
    required this.name,
    required this.title,
    required this.summary,
    required this.apiBasePath,
    required this.phoneChannel,
    required this.workflowPlaceholder,
    required this.profileSource,
    required this.marketConnected,
    required this.marketPkgId,
    required this.marketVersion,
    required this.marketAuthor,
    required this.marketMaterialCategory,
    required this.marketLicenseScope,
    required this.marketSecurityLevel,
    this.avatarUrl,
  });

  final String modId;
  final String modName;
  final String modDescription;
  final String modVersion;
  final String modAuthor;
  final String industryName;
  final String employeeId;
  final String name;
  final String title;
  final String summary;
  final String apiBasePath;
  final String phoneChannel;
  final bool workflowPlaceholder;
  final String profileSource;
  final bool marketConnected;
  final String marketPkgId;
  final String marketVersion;
  final String marketAuthor;
  final String marketMaterialCategory;
  final String marketLicenseScope;
  final String marketSecurityLevel;
  final String? avatarUrl;

  String get key => '$modId:$employeeId';

  String get sourceLabel {
    if (marketPkgId.trim().isNotEmpty) {
      return 'AI市场 · ${modName.ifEmpty('已安装员工')}';
    }
    if (modName.trim().isNotEmpty) return modName.trim();
    if (profileSource.trim().isNotEmpty) return profileSource.trim();
    return '当前账号生态';
  }

  List<String> abilityLabels() {
    final labels = <String>[];
    if (phoneChannel.trim().isNotEmpty) labels.add('可对话');
    if (apiBasePath.trim().isNotEmpty) labels.add('可执行任务');
    if (industryName.trim().isNotEmpty) labels.add(industryName.trim());
    if (workflowPlaceholder) labels.add('待完善');
    if (marketPkgId.trim().isNotEmpty) labels.add('市场资料');
    if (labels.isEmpty) labels.add('生态同步');
    return labels.take(4).toList(growable: false);
  }

  String get contactLine {
    return [
      _contactChannelLabel(phoneChannel),
      employeeId.trim().isNotEmpty ? 'AI号 ${employeeId.trim()}' : '',
      apiBasePath.trim().isNotEmpty ? '入口 ${apiBasePath.trim()}' : '',
    ].where((value) => value.trim().isNotEmpty).join(' · ');
  }
}

List<AiEmployeeProfile> aiEmployeeProfilesFromMods(List<ModInfo> mods) {
  final profiles = <AiEmployeeProfile>[];
  final seenKeys = <String>{};

  for (final mod in mods) {
    for (final employee in mod.workflowEmployees) {
      final employeeId = employee.id.trim();
      final name = employee.label
          .ifEmpty(employee.panelTitle)
          .ifEmpty(employeeId)
          .trim();
      if (employeeId.isEmpty || name.isEmpty) continue;

      final profile = AiEmployeeProfile(
        modId: mod.id,
        modName: mod.name.ifEmpty(mod.id),
        modDescription: mod.description,
        modVersion: employee.marketVersion.ifEmpty(mod.version),
        modAuthor: employee.marketAuthor.ifEmpty(mod.author),
        industryName: employee.marketIndustry.ifEmpty(mod.industry?.name ?? ''),
        employeeId: employeeId,
        name: name,
        title: employee.panelTitle.ifEmpty(name),
        summary:
            employee.marketDescription.ifEmpty(employee.panelSummary).ifEmpty(
                  mod.description.ifEmpty(
                    '由当前账号生态的 ${mod.name.ifEmpty(mod.id)} 同步到手机端。',
                  ),
                ),
        apiBasePath: employee.apiBasePath,
        phoneChannel: employee.phoneChannel,
        workflowPlaceholder: employee.workflowPlaceholder,
        profileSource: employee.profileSource,
        marketConnected: employee.marketConnected,
        marketPkgId: employee.marketPkgId,
        marketVersion: employee.marketVersion,
        marketAuthor: employee.marketAuthor,
        marketMaterialCategory: employee.marketMaterialCategory,
        marketLicenseScope: employee.marketLicenseScope,
        marketSecurityLevel: employee.marketSecurityLevel,
        avatarUrl: _nonBlankOrNull(employee.marketAvatar) ??
            _nonBlankOrNull(mod.avatarUrl),
      );
      if (seenKeys.add(profile.key)) profiles.add(profile);
    }
  }

  return profiles;
}

List<AiEmployeeProfile> adminDutyEmployeeProfiles([
  List<DutyRosterEmployee> employees = adminDutyRosterEmployees,
]) {
  return employees
      .where((employee) => employee.id.trim().isNotEmpty)
      .map(
        (employee) => AiEmployeeProfile(
          modId: adminDutyModId,
          modName: '管理端 AI 员工',
          modDescription: '管理端 duty AI 员工',
          modVersion: '10.0',
          modAuthor: 'XCAGI 管理端',
          industryName: '管理端',
          employeeId: employee.id.trim(),
          name: employee.label.ifEmpty(employee.id),
          title: employee.label.ifEmpty(employee.id),
          summary: employee.summary.ifEmpty('管理端 duty AI 员工'),
          apiBasePath: '/api/admin/employees/${employee.id.trim()}',
          phoneChannel: 'admin-duty',
          workflowPlaceholder: false,
          profileSource: 'duty_roster',
          marketConnected: false,
          marketPkgId: '',
          marketVersion: '',
          marketAuthor: '',
          marketMaterialCategory: '',
          marketLicenseScope: '',
          marketSecurityLevel: '',
        ),
      )
      .toList(growable: false);
}

String _contactChannelLabel(String value) {
  switch (value.trim()) {
    case 'admin-duty':
      return '管理端工作台';
    case 'mobile':
    case 'mobile-chat':
      return '手机端会话';
    case '':
      return '';
    default:
      return value.trim();
  }
}

String? _nonBlankOrNull(String? value) {
  final trimmed = value?.trim() ?? '';
  return trimmed.isEmpty ? null : trimmed;
}
