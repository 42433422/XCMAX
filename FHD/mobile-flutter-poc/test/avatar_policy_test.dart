import 'dart:io';

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
      _androidPinnedIds(),
      reason: 'Flutter fixed conversation ids must mirror Android PinnedIds.',
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

  test('AI group fixed member ids mirror Android catalog constants', () {
    expect(
      {
        'XIAOC_ASSISTANT_EMPLOYEE_ID': AiGroupMemberIds.xiaocAssistant,
        'CODEX_SUPER_EMPLOYEE_ID': AiGroupMemberIds.codexSuperEmployee,
        'CURSOR_SUPER_EMPLOYEE_ID': AiGroupMemberIds.cursorSuperEmployee,
        'CLAUDE_SUPER_EMPLOYEE_ID': AiGroupMemberIds.claudeSuperEmployee,
        'TRAE_SUPER_EMPLOYEE_ID': AiGroupMemberIds.traeSuperEmployee,
      },
      _androidAiGroupMemberIds(),
      reason:
          'Flutter fixed AI group member ids must mirror Android AiGroupMemberCatalog.kt.',
    );
  });

  test('chat avatar fallback follows Android pinned conversation policy', () {
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

  test('employee avatar fallback mirrors Android employee id mapping', () {
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

  test('avatar fallback enum assets mirror Android AppAvatar drawable table',
      () {
    expect(
      AppAvatarFallback.values.map((fallback) => fallback.assetPath).toList(),
      _androidAvatarAssetPaths(),
      reason:
          'Flutter avatar fallback assets must mirror Android AppAvatar.kt.',
    );
  });

  test('employee avatar fallback table mirrors Android source table', () {
    final androidDrawables = _androidAvatarDrawableByFallback();
    final androidEmployeeFallbacks = _androidEmployeeAvatarFallbackMap();

    for (final entry in androidEmployeeFallbacks.entries) {
      final expectedDrawable = androidDrawables[entry.value];
      if (expectedDrawable == null) {
        throw StateError('Android fallback ${entry.value} has no drawable');
      }
      final expectedAsset = 'assets/avatars/$expectedDrawable.png';
      expect(
        employeeAvatarFallback(employeeId: entry.key).assetPath,
        expectedAsset,
        reason: 'Employee avatar fallback drifted for ${entry.key}',
      );
      expect(
        employeeAvatarFallback(employeeId: entry.key.replaceAll('-', '_'))
            .assetPath,
        expectedAsset,
        reason: 'Employee avatar underscore fallback drifted for ${entry.key}',
      );
    }
  });

  test('local account avatar fallback uses Android user asset', () {
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

  test('super employee routing policy matches Android relay policy', () {
    expect(relayKindForConversation(PinnedIds.codex), 'codex.invoke');
    expect(relayKindForConversation(PinnedIds.cursor), 'cursor.invoke');
    expect(relayKindForConversation(PinnedIds.claude), 'claude.invoke');
    expect(relayKindForConversation(PinnedIds.trae), 'trae.invoke');
    expect(relayKindForConversation(PinnedIds.assistant), isNull);
  });

  test('super employee messages path matches Android endpoints', () {
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

Map<String, String> _androidPinnedIds() {
  final source = File(
    '../mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/model/ConversationItem.kt',
  ).readAsStringSync();
  return {
    for (final match in RegExp(
      r'const val\s+([A-Z0-9_]+)\s*=\s*"([^"]+)"',
    ).allMatches(source))
      match.group(1)!: match.group(2)!,
  };
}

Map<String, String> _androidAiGroupMemberIds() {
  final source = File(
    '../mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/navigation/AiGroupMemberCatalog.kt',
  ).readAsStringSync();
  return {
    for (final match in RegExp(
      r'internal const val\s+([A-Z0-9_]+)\s*=\s*"([^"]+)"',
    ).allMatches(source))
      match.group(1)!: match.group(2)!,
  };
}

List<String> _androidAvatarAssetPaths() {
  return _androidAvatarDrawableByFallback()
      .values
      .map((drawable) => 'assets/avatars/$drawable.png')
      .toList(growable: false);
}

Map<String, String> _androidAvatarDrawableByFallback() {
  final source = File(
    '../mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/ui/components/mobile/AppAvatar.kt',
  ).readAsStringSync();
  return {
    for (final match in RegExp(
      r'([A-Z0-9_]+)\(R\.drawable\.([a-z0-9_]+)\)',
    ).allMatches(source))
      match.group(1)!: match.group(2)!,
  };
}

Map<String, String> _androidEmployeeAvatarFallbackMap() {
  final source = File(
    '../mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/ui/components/mobile/EmployeeAvatarFallbacks.kt',
  ).readAsStringSync();
  return {
    for (final match in RegExp(
      r'"([^"]+)"\s+to\s+AppAvatarFallback\.([A-Z0-9_]+)',
    ).allMatches(source))
      match.group(1)!: match.group(2)!,
  };
}
