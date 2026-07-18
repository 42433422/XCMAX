import 'package:flutter_test/flutter_test.dart';
import 'package:xcagi_flutter_poc/src/models/conversation.dart';
import 'package:xcagi_flutter_poc/src/policy/avatar_policy.dart';
import 'package:xcagi_flutter_poc/src/policy/pinned_ids.dart';

void main() {
  test('fixed conversation ids map to fixed conversation types', () {
    expect(
      {
        'CS': PinnedIds.cs,
        'ASSISTANT': PinnedIds.assistant,
        'CODEX': PinnedIds.codex,
        'CURSOR': PinnedIds.cursor,
        'CLAUDE': PinnedIds.claude,
        'TRAE': PinnedIds.trae,
      },
      {
        'CS': 'pinned:cs',
        'ASSISTANT': 'pinned:assistant',
        'CODEX': 'pinned:codex',
        'CURSOR': 'pinned:cursor',
        'CLAUDE': 'pinned:claude',
        'TRAE': 'pinned:trae',
      },
    );
    expect(
      conversationTypeForFixed(id: PinnedIds.assistant),
      ConversationType.pinnedAssistant,
    );
    expect(
      conversationTypeForFixed(id: PinnedIds.codex),
      ConversationType.pinnedCodex,
    );
    expect(
      conversationTypeForFixed(id: PinnedIds.cursor),
      ConversationType.pinnedCursor,
    );
    expect(
      conversationTypeForFixed(id: PinnedIds.claude),
      ConversationType.pinnedClaude,
    );
    expect(
      conversationTypeForFixed(id: PinnedIds.trae),
      ConversationType.pinnedTrae,
    );
  });

  test('AI group fixed member ids match the Flutter contract', () {
    expect(
      {
        'XIAOC_ASSISTANT_EMPLOYEE_ID': AiGroupMemberIds.xiaocAssistant,
        'CODEX_SUPER_EMPLOYEE_ID': AiGroupMemberIds.codexSuperEmployee,
        'CURSOR_SUPER_EMPLOYEE_ID': AiGroupMemberIds.cursorSuperEmployee,
        'CLAUDE_SUPER_EMPLOYEE_ID': AiGroupMemberIds.claudeSuperEmployee,
        'TRAE_SUPER_EMPLOYEE_ID': AiGroupMemberIds.traeSuperEmployee,
      },
      {
        'XIAOC_ASSISTANT_EMPLOYEE_ID': 'xcagi-assistant',
        'CODEX_SUPER_EMPLOYEE_ID': 'codex-super-employee',
        'CURSOR_SUPER_EMPLOYEE_ID': 'cursor-super-employee',
        'CLAUDE_SUPER_EMPLOYEE_ID': 'claude-super-employee',
        'TRAE_SUPER_EMPLOYEE_ID': 'trae-super-employee',
      },
    );
  });

  test('chat avatar fallback follows the pinned conversation policy', () {
    expect(
      chatAvatarFallback(
        conversationId: PinnedIds.codex,
        hasEmployeeProfile: false,
      ),
      AppAvatarFallback.codex,
    );
    expect(
      chatAvatarFallback(
        conversationId: 'employee:admin-duty:site-content-editor',
        hasEmployeeProfile: true,
      ),
      AppAvatarFallback.empSiteContentEditor,
    );
    expect(
      chatAvatarFallback(conversationId: 'default', hasEmployeeProfile: false),
      AppAvatarFallback.assistant,
    );
  });

  test('ai group avatar fallback detects fixed super employees', () {
    expect(
      aiGroupAvatarFallback(
        employeeId: AiGroupMemberIds.xiaocAssistant,
        name: '小C助理',
      ),
      AppAvatarFallback.assistant,
    );
    expect(
      aiGroupAvatarFallback(employeeId: 'worker-1', avatarKey: 'cursor'),
      AppAvatarFallback.cursor,
    );
    expect(
      aiGroupAvatarFallback(employeeId: 'worker-2', name: '超级员工-Claude'),
      AppAvatarFallback.claude,
    );
    expect(
      aiGroupAvatarFallback(employeeId: 'worker-3'),
      AppAvatarFallback.aiEmployee,
    );
  });

  test('employee avatar fallback normalizes employee ids', () {
    expect(
      employeeAvatarFallback(
        employeeId: 'employee:admin-duty:site-content-editor',
      ),
      AppAvatarFallback.empSiteContentEditor,
    );
    expect(
      employeeAvatarFallback(employeeId: 'seo_sitemap_curator'),
      AppAvatarFallback.empSeoSitemapCurator,
    );
    expect(
      employeeAvatarFallback(employeeId: 'avatar-generation-employee'),
      AppAvatarFallback.empAvatarGenerationEmployee,
    );
  });

  test('all Flutter avatar fallbacks resolve to bundled assets', () {
    for (final fallback in AppAvatarFallback.values) {
      expect(fallback.assetPath, startsWith('assets/avatars/'));
      expect(fallback.assetPath, endsWith('.png'));
    }
    expect(
      AppAvatarFallback.user.assetPath,
      'assets/avatars/avatar_default_user.png',
    );
    expect(
      AppAvatarFallback.values.any(
        (fallback) => fallback.assetPath.contains('avatar_admin_profile'),
      ),
      isFalse,
    );
  });

  test('super employee routing policy matches the relay contract', () {
    expect(relayKindForConversation(PinnedIds.codex), 'codex.invoke');
    expect(relayKindForConversation(PinnedIds.cursor), 'cursor.invoke');
    expect(relayKindForConversation(PinnedIds.claude), 'claude.invoke');
    expect(relayKindForConversation(PinnedIds.trae), 'trae.invoke');
    expect(relayKindForConversation(PinnedIds.assistant), isNull);
  });

  test('super employee messages path matches the mobile API contract', () {
    expect(
      superEmployeeMessagesPath(PinnedIds.codex),
      'api/mobile/v1/admin/codex-super-employee/messages',
    );
    expect(
      superEmployeeMessagesPath(PinnedIds.claude),
      'api/mobile/v1/admin/claude-super-employee/messages',
    );
    expect(
      superEmployeeMessagesPath(PinnedIds.cursor),
      'api/mobile/v1/admin/cursor-super-employee/messages',
    );
    expect(
      superEmployeeMessagesPath(PinnedIds.trae),
      'api/mobile/v1/admin/trae-super-employee/messages',
    );
  });
}
