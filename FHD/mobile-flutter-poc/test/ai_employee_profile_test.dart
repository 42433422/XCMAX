import 'package:flutter_test/flutter_test.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_models.dart';
import 'package:xcagi_flutter_poc/src/data/ai_employee_profile.dart';
import 'package:xcagi_flutter_poc/src/data/duty_roster_ssot.dart';

void main() {
  test('AI employee profile preserves Android workflow employee fields', () {
    final profiles = aiEmployeeProfilesFromMods([
      const ModInfo(
        id: 'avatar-mod',
        name: '头像员工包',
        version: '1.2.3',
        description: '生成头像',
        author: 'XCAGI',
        primary: true,
        industry: ModIndustry(id: 'image', name: '图像'),
        avatarUrl: 'https://cdn.example.com/mod.png',
        frontendMenu: [],
        workflowEmployees: [
          WorkflowEmployeeInfo(
            id: 'avatar-generation-employee',
            label: '头像生成员工',
            panelTitle: '头像设计师',
            panelSummary: '给 AI 员工生成头像',
            apiBasePath: '/api/avatar',
            phoneChannel: 'mobile-chat',
            workflowPlaceholder: false,
            profileSource: 'market',
            marketConnected: true,
            marketPkgId: 'avatar-generation-employee',
            marketName: '头像生成员工',
            marketDescription: '从市场同步的头像生成资料',
            marketVersion: '1.0.0',
            marketAuthor: 'XCAGI',
            marketIndustry: '视觉',
            marketMaterialCategory: 'AI 员工',
            marketLicenseScope: 'enterprise',
            marketSecurityLevel: 'standard',
            marketAvatar: 'https://cdn.example.com/employee.png',
          ),
        ],
      ),
    ]);

    expect(profiles, hasLength(1));
    final profile = profiles.single;
    expect(profile.key, 'avatar-mod:avatar-generation-employee');
    expect(profile.name, '头像生成员工');
    expect(profile.title, '头像设计师');
    expect(profile.summary, '从市场同步的头像生成资料');
    expect(profile.avatarUrl, 'https://cdn.example.com/employee.png');
    expect(profile.sourceLabel, 'AI市场 · 头像员工包');
    expect(profile.contactLine,
        '手机端会话 · AI号 avatar-generation-employee · 入口 /api/avatar');
    expect(profile.abilityLabels(), ['可对话', '可执行任务', '视觉', '市场资料']);
  });

  test('AI employee profile mirrors Android fallback summary and avatar source',
      () {
    final profiles = aiEmployeeProfilesFromMods([
      const ModInfo(
        id: 'ops-mod',
        name: '运维员工包',
        version: '1.0.0',
        description: '',
        author: 'XCAGI',
        primary: false,
        industry: null,
        avatarUrl: 'https://cdn.example.com/mod-avatar.png',
        frontendMenu: [],
        workflowEmployees: [
          WorkflowEmployeeInfo(
            id: 'host-checker',
            label: '运维员工',
            panelTitle: '',
            panelSummary: '',
            apiBasePath: '',
            phoneChannel: '',
            workflowPlaceholder: false,
            profileSource: '',
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
            marketAvatar: '   ',
          ),
        ],
      ),
    ]);

    expect(profiles.single.summary, '由当前账号生态的 运维员工包 同步到手机端。');
    expect(profiles.single.avatarUrl, 'https://cdn.example.com/mod-avatar.png');
  });

  test('admin duty fallback profiles match Android contact line defaults', () {
    final profiles = adminDutyEmployeeProfiles(const [
      DutyRosterEmployee(
        id: 'site-content-editor',
        label: '静态站内容编辑员',
        summary: '维护 xiu-ci.com 内容',
      ),
    ]);

    expect(profiles.single.sourceLabel, '管理端 AI 员工');
    expect(profiles.single.contactLine,
        '管理端工作台 · AI号 site-content-editor · 入口 /api/admin/employees/site-content-editor');
  });
}
