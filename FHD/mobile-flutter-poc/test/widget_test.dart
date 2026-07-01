import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:xcagi_flutter_poc/src/api/mobile_api.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_models.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_session_store.dart';
import 'package:xcagi_flutter_poc/src/data/ai_group_snapshot.dart';
import 'package:xcagi_flutter_poc/src/data/ai_employee_profile.dart';
import 'package:xcagi_flutter_poc/src/data/demo_data.dart';
import 'package:xcagi_flutter_poc/src/data/duty_roster_ssot.dart';
import 'package:xcagi_flutter_poc/src/data/mobile_repository.dart';
import 'package:xcagi_flutter_poc/src/models/conversation.dart';
import 'package:xcagi_flutter_poc/src/features/about/about_screen.dart';
import 'package:xcagi_flutter_poc/src/features/approval/approval_screens.dart';
import 'package:xcagi_flutter_poc/src/features/auth/auth_screen.dart';
import 'package:xcagi_flutter_poc/src/features/auth/register_screen.dart';
import 'package:xcagi_flutter_poc/src/features/bridge/bridge_screen.dart';
import 'package:xcagi_flutter_poc/src/features/business/business_screens.dart';
import 'package:xcagi_flutter_poc/src/features/circle/ai_circle_screen.dart';
import 'package:xcagi_flutter_poc/src/features/chat/chat_screen.dart';
import 'package:xcagi_flutter_poc/src/features/connect/connect_screen.dart';
import 'package:xcagi_flutter_poc/src/features/contacts/contacts_screen.dart';
import 'package:xcagi_flutter_poc/src/features/contacts/employee_profile_screen.dart';
import 'package:xcagi_flutter_poc/src/features/contacts/fixed_partner_profile_screen.dart';
import 'package:xcagi_flutter_poc/src/features/cs/cs_chat_screen.dart';
import 'package:xcagi_flutter_poc/src/features/discover/discover_screen.dart';
import 'package:xcagi_flutter_poc/src/features/enterprise/enterprise_module_screen.dart';
import 'package:xcagi_flutter_poc/src/features/finance/longtail_screen.dart';
import 'package:xcagi_flutter_poc/src/features/groups/ai_group_screens.dart';
import 'package:xcagi_flutter_poc/src/features/im/im_messenger_screen.dart';
import 'package:xcagi_flutter_poc/src/features/legal/legal_consent_screen.dart';
import 'package:xcagi_flutter_poc/src/features/market/market_list_screen.dart';
import 'package:xcagi_flutter_poc/src/features/messages/message_list_screen.dart';
import 'package:xcagi_flutter_poc/src/features/notifications/notification_list_screen.dart';
import 'package:xcagi_flutter_poc/src/features/onboarding/mobile_onboarding_screen.dart';
import 'package:xcagi_flutter_poc/src/features/profile/profile_screen.dart';
import 'package:xcagi_flutter_poc/src/features/scan/scan_qr_screen.dart';
import 'package:xcagi_flutter_poc/src/features/settings/settings_screen.dart';
import 'package:xcagi_flutter_poc/src/features/shell/home_shell.dart';
import 'package:xcagi_flutter_poc/src/features/tools/ocr_screen.dart';
import 'package:xcagi_flutter_poc/src/features/update/android_package_update_installer.dart';
import 'package:xcagi_flutter_poc/src/features/webview/desktop_tool_webview_screen.dart';
import 'package:xcagi_flutter_poc/src/policy/android_runtime_policy.dart';
import 'package:xcagi_flutter_poc/src/policy/avatar_policy.dart';
import 'package:xcagi_flutter_poc/src/policy/pinned_ids.dart';
import 'package:xcagi_flutter_poc/src/theme/app_assets.dart';
import 'package:xcagi_flutter_poc/src/theme/app_theme.dart';
import 'package:xcagi_flutter_poc/src/theme/message_avatar_layout.dart';
import 'package:xcagi_flutter_poc/src/widgets/app_avatar.dart';
import 'package:xcagi_flutter_poc/src/widgets/group_grid_avatar.dart';
import 'package:xcagi_flutter_poc/src/widgets/we_ui.dart';

void main() {
  setUp(AndroidProductSkuConfig.resetRemoteSku);

  test('pairing QR parser follows Android short-code priority', () {
    final shortCode = parsePairingPayload('123456')!;
    expect(shortCode.code, '123456');
    expect(shortCode.token, '123456');
    expect(shortCode.version, 2);

    final deeplink = parsePairingPayload(
      'xcagi://pair?nonce=abcdef123456&code=654321&host=192.168.31.8&port=5112',
    )!;
    expect(deeplink.code, '654321');
    expect(deeplink.nonce, 'abcdef123456');
    expect(deeplink.host, '192.168.31.8');
    expect(deeplink.port, 5112);
    expect(deeplink.hostWithPort, '192.168.31.8:5112');

    final json =
        parsePairingPayload('{"v":2,"nonce":"abcdef123456","token":"789012"}')!;
    expect(json.code, '789012');

    final relay = parsePairingPayload(
      '{"v":3,"kind":"relay","relay_id":"relay-1","relay_base_url":"https://xiu-ci.com/fhd-api","code":"345678"}',
    )!;
    expect(relay.version, 3);
    expect(relay.relayId, 'relay-1');
    expect(relay.relayBaseUrl, 'https://xiu-ci.com/fhd-api');

    expect(parsePairingPayload(''), isNull);
    expect(parsePairingPayload('xcagi://open?nonce=abcdef123456'), isNull);
    expect(parsePairingPayload('https://xiu-ci.com/auth-qr?qr_id=1'), isNull);
    expect(parsePairingPayload('not-a-pairing-code'), isNull);
    expect(parsePairingPayload('{"v":1,"nonce":"short"}'), isNull);
  });

  test('auth QR parser follows web login qr payload', () {
    final payload = parseAuthQrPayload(
      'https://xiu-ci.com/auth-qr?qr_id=login-123&account_kind=admin',
    );

    expect(payload?.qrId, 'login-123');
    expect(payload?.accountKind, 'admin');
    expect(parseAuthQrPayload('xcagi://pair?code=123456'), isNull);
  });

  test('theme tokens mirror Android Theme.kt constants', () {
    // Keep Flutter locked to mobile-android/ui/theme/Theme.kt.
    final light = AppTheme.light();
    final dark = AppTheme.dark();
    const lightExtra = XcagiThemeColors.light;
    const darkExtra = XcagiThemeColors.dark;

    expect(light.colorScheme.primary, const Color(0xFF6366F1));
    expect(light.colorScheme.primaryContainer, const Color(0xFFEAEBFE));
    expect(light.colorScheme.onPrimaryContainer, const Color(0xFF312E81));
    expect(light.colorScheme.secondary, const Color(0xFF10B981));
    expect(light.colorScheme.secondaryContainer, const Color(0xFFE7FAF3));
    expect(light.colorScheme.onSecondaryContainer, const Color(0xFF064E3B));
    expect(light.colorScheme.surface, const Color(0xFFFFFFFF));
    expect(light.colorScheme.onSurface, const Color(0xFF1F2329));
    expect(light.colorScheme.surfaceContainerHighest, const Color(0xFFE8E9EB));
    expect(light.colorScheme.outlineVariant, const Color(0xFFDEE0E3));
    expect(light.colorScheme.error, const Color(0xFFEF4444));
    expect(light.colorScheme.errorContainer, const Color(0xFFFFECEC));
    expect(light.scaffoldBackgroundColor, const Color(0xFFF5F6F7));
    expect(lightExtra.brandGradientEnd, const Color(0xFF7C3AED));
    expect(lightExtra.weChatOnline, const Color(0xFF10B981));
    expect(lightExtra.chatUserBubble, const Color(0xFF6366F1));
    expect(lightExtra.chatUserBubbleText, const Color(0xFFFFFFFF));
    expect(lightExtra.momentAccent, const Color(0xFF5145CD));
    expect(lightExtra.momentChipBg, const Color(0xFFECEDFE));
    expect(lightExtra.replyBoxBg, const Color(0xFFF4F5F7));
    expect(lightExtra.textSecondary, const Color(0xFF646A73));
    expect(lightExtra.textTertiary, const Color(0xFF8F959E));

    expect(dark.colorScheme.primary, const Color(0xFF818CF8));
    expect(dark.colorScheme.primaryContainer, const Color(0xFF1A3A80));
    expect(dark.colorScheme.onPrimaryContainer, const Color(0xFFB8CCFF));
    expect(dark.colorScheme.secondary, const Color(0xFF10B981));
    expect(dark.colorScheme.secondaryContainer, const Color(0xFF005B3F));
    expect(dark.colorScheme.onSecondaryContainer, const Color(0xFF34D399));
    expect(dark.colorScheme.surface, const Color(0xFF242424));
    expect(dark.colorScheme.onSurface, const Color(0xFFE5E5E5));
    expect(dark.colorScheme.surfaceContainerHighest, const Color(0xFF2E2E2E));
    expect(dark.colorScheme.outlineVariant, const Color(0xFF2E2E2E));
    expect(dark.colorScheme.error, const Color(0xFFEF4444));
    expect(dark.colorScheme.errorContainer, const Color(0xFF5C1A1A));
    expect(dark.scaffoldBackgroundColor, const Color(0xFF1A1A1A));
    expect(darkExtra.brandGradientEnd, const Color(0xFF3F6FD8));
    expect(darkExtra.weChatOnline, const Color(0xFF34D399));
    expect(darkExtra.chatUserBubble, const Color(0xFF4F46E5));
    expect(darkExtra.chatUserBubbleText, const Color(0xFFEEF0FF));
    expect(darkExtra.momentAccent, const Color(0xFFA5B0FF));
    expect(darkExtra.momentChipBg, const Color(0xFF2A2A3D));
    expect(darkExtra.replyBoxBg, const Color(0xFF26262E));
    expect(darkExtra.textSecondary, const Color(0xFF888888));
    expect(darkExtra.textTertiary, const Color(0xFF5C5C5C));
  });

  testWidgets('message list renders Android-first department groups', (
    WidgetTester tester,
  ) async {
    tester.view.devicePixelRatio = 1;
    tester.view.physicalSize = const Size(430, 1800);
    addTearDown(tester.view.resetDevicePixelRatio);
    addTearDown(tester.view.resetPhysicalSize);

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: Scaffold(
          body: MessageListScreen(
            groups: liveAiGroupSnapshot,
            items: demoConversations,
          ),
        ),
      ),
    );

    expect(find.text('admin'), findsOneWidget);
    expect(find.text('管理员账号 · 55位AI员工'), findsOneWidget);
    expect(find.text('查找会话或伙伴'), findsOneWidget);
    expect(find.text('超级开发部'), findsOneWidget);
    expect(find.text('(5)'), findsOneWidget);
    expect(find.text('P-W 网站部'), findsOneWidget);
    expect(find.text('小C助理'), findsWidgets);
    expect(find.text('超级员工-Codex'), findsWidgets);

    final headerPadding = tester.widget<Padding>(
      find.byKey(const ValueKey('message_home_header_padding')),
    );
    expect(
      headerPadding.padding,
      const EdgeInsets.fromLTRB(16, 8, 16, 10),
    );
    final searchGap = tester.widget<SizedBox>(
      find.byKey(const ValueKey('message_home_header_search_gap')),
    );
    expect(searchGap.height, 12);
    final rowDividers = tester.widgetList<Divider>(find.byType(Divider)).where(
          (divider) =>
              divider.indent == MessageAvatarLayout.conversationDividerStart,
        );
    expect(rowDividers, isNotEmpty);
    expect(rowDividers.first.height, 0.5);
    expect(rowDividers.first.thickness, 0.5);
    expect(
        rowDividers.first.color, AppTheme.light().colorScheme.outlineVariant);
  });

  testWidgets('message list text styles use Android typography tokens', (
    WidgetTester tester,
  ) async {
    const readConversation = ConversationItem(
      id: 'employee:demo:read-style',
      type: ConversationType.aiTask,
      title: '已读员工样式',
      subtitle: '已读预览样式',
      timestampText: '6/24',
    );
    final typography = AppTheme.light().textTheme;

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: Scaffold(
          body: MessageListScreen(
            groups: [_fakeGroup.copyWith(isPinned: true, isFollowed: false)],
            items: const [readConversation, _fakeUnreadConversation],
          ),
        ),
      ),
    );

    final headerTitle = tester.widget<Text>(find.text('admin'));
    expect(headerTitle.style?.fontSize, typography.titleLarge?.fontSize);
    expect(headerTitle.style?.height, typography.titleLarge?.height);
    expect(headerTitle.style?.fontWeight, FontWeight.w600);

    final headerSubtitle = tester.widget<Text>(
      find.text('管理员账号 · 2位AI员工'),
    );
    expect(headerSubtitle.style?.fontSize, typography.labelMedium?.fontSize);
    expect(headerSubtitle.style?.height, typography.labelMedium?.height);

    final searchField = tester.widget<TextField>(find.byType(TextField));
    expect(searchField.style?.fontSize, typography.bodyMedium?.fontSize);
    expect(searchField.style?.height, typography.bodyMedium?.height);
    expect(
      searchField.decoration?.hintStyle?.fontSize,
      typography.bodyMedium?.fontSize,
    );

    final groupTitle = tester.widget<Text>(find.text('超级开发部'));
    expect(groupTitle.style?.fontSize, typography.bodyLarge?.fontSize);
    expect(groupTitle.style?.height, typography.bodyLarge?.height);
    expect(groupTitle.style?.fontWeight, FontWeight.w500);

    final groupCount = tester.widget<Text>(find.text('(2)'));
    expect(groupCount.style?.fontSize, typography.labelMedium?.fontSize);
    expect(groupCount.style?.height, typography.labelMedium?.height);

    final groupPreview = tester.widget<Text>(find.text('先评估任务，再派给最合适的人。'));
    expect(groupPreview.style?.fontSize, typography.bodySmall?.fontSize);
    expect(groupPreview.style?.height, typography.bodySmall?.height);

    final followedLabel = tester.widget<Text>(find.text('不再关注'));
    expect(followedLabel.style?.fontSize, 10);
    expect(followedLabel.style?.height, typography.labelSmall?.height);

    final readTitle = tester.widget<Text>(find.text('已读员工样式'));
    expect(readTitle.style?.fontSize, typography.titleMedium?.fontSize);
    expect(readTitle.style?.height, typography.titleMedium?.height);
    expect(readTitle.style?.fontWeight, FontWeight.w600);

    final timestamp = tester.widget<Text>(find.text('6/24'));
    expect(timestamp.style?.fontSize, typography.labelMedium?.fontSize);
    expect(timestamp.style?.height, typography.labelMedium?.height);

    final subtitle = tester.widget<Text>(find.text('已读预览样式'));
    expect(subtitle.style?.fontSize, typography.bodyMedium?.fontSize);
    expect(subtitle.style?.height, typography.bodyMedium?.height);

    final unreadTitle = tester.widget<Text>(find.text('客户会话'));
    expect(unreadTitle.style?.fontSize, typography.titleMedium?.fontSize);
    expect(unreadTitle.style?.height, typography.titleMedium?.height);
    expect(unreadTitle.style?.fontWeight, FontWeight.w700);
  });

  testWidgets('message list plus menu follows Android destinations', (
    WidgetTester tester,
  ) async {
    final opened = <String>[];

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: Scaffold(
          body: MessageListScreen(
            items: const [],
            onStartGroupChat: () => opened.add('group'),
            onOpenGroups: () => opened.add('groups'),
            onOpenScan: () => opened.add('scan'),
            onOpenEmployees: () => opened.add('employees'),
            onOpenContacts: () => opened.add('contacts'),
            onOpenDiscover: () => opened.add('discover'),
          ),
        ),
      ),
    );

    final menuButton = tester.widget<PopupMenuButton<String>>(
      find.byType(PopupMenuButton<String>),
    );
    expect(menuButton.constraints, const BoxConstraints.tightFor(width: 188));
    expect(menuButton.menuPadding, EdgeInsets.zero);
    expect(
      tester.getSize(find.byKey(const ValueKey('message_header_plus_button'))),
      const Size(48, 48),
    );
    final headerPlusIcon = tester.widget<Icon>(
      find.descendant(
        of: find.byKey(const ValueKey('message_header_plus_button')),
        matching: find.byIcon(Icons.add),
      ),
    );
    expect(headerPlusIcon.size, 24);

    await tester.tap(find.byTooltip('更多'));
    await tester.pumpAndSettle();

    final firstMenuRow = tester.widget<Padding>(
      find.byKey(const ValueKey('message_plus_menu_row_发起群聊')),
    );
    expect(
      firstMenuRow.padding,
      const EdgeInsets.symmetric(horizontal: 16, vertical: 11),
    );
    final firstMenuIcon = tester.widget<Icon>(
      find.descendant(
        of: find.byKey(const ValueKey('message_plus_menu_row_发起群聊')),
        matching: find.byIcon(Icons.groups),
      ),
    );
    expect(firstMenuIcon.size, 20);
    expect(firstMenuIcon.color, AppTheme.brand);
    await tester.tapAt(const Offset(1, 1));
    await tester.pumpAndSettle();

    await _tapHeaderPlusMenuItem(tester, '发起群聊');
    await _tapHeaderPlusMenuItem(tester, '我的群聊');
    await _tapHeaderPlusMenuItem(tester, '扫一扫');
    await _tapHeaderPlusMenuItem(tester, 'AI 员工');
    await _tapHeaderPlusMenuItem(tester, '通讯录');
    await _tapHeaderPlusMenuItem(tester, '交流圈');

    expect(opened, [
      'group',
      'groups',
      'scan',
      'employees',
      'contacts',
      'discover',
    ]);
    expect(find.byType(SnackBar), findsNothing);
  });

  testWidgets('message list conversation long press mirrors Android actions', (
    WidgetTester tester,
  ) async {
    final repository = _FakeConversationActionRepository();
    var refreshCount = 0;

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: Scaffold(
          body: MessageListScreen(
            items: const [_fakeUnreadConversation],
            repository: repository,
            onRefresh: () async {
              refreshCount += 1;
            },
          ),
        ),
      ),
    );

    await tester.longPress(find.text('客户会话'));
    await tester.pumpAndSettle();

    expect(find.text('标为已读'), findsOneWidget);
    expect(find.text('取消置顶'), findsOneWidget);
    expect(find.text('不再关注'), findsOneWidget);
    expect(find.text('不显示该聊天'), findsOneWidget);
    expect(find.text('删除该聊天'), findsOneWidget);

    await tester.tap(find.text('标为已读'));
    await tester.pumpAndSettle();

    expect(repository.actions, ['conversation-read:employee:demo:customer']);
    expect(refreshCount, 1);
  });

  testWidgets('message list group long press uses Android group operations', (
    WidgetTester tester,
  ) async {
    final repository = _FakeConversationActionRepository();
    var refreshCount = 0;

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: Scaffold(
          body: MessageListScreen(
            groups: const [_fakeGroup],
            items: const [],
            repository: repository,
            onRefresh: () async {
              refreshCount += 1;
            },
          ),
        ),
      ),
    );

    await tester.longPress(find.text('超级开发部'));
    await tester.pumpAndSettle();

    expect(find.text('标为未读'), findsOneWidget);
    expect(find.text('置顶聊天'), findsOneWidget);
    expect(find.text('不再关注'), findsOneWidget);
    expect(find.text('不显示该聊天'), findsOneWidget);
    expect(find.text('删除该聊天'), findsOneWidget);

    await tester.tap(find.text('置顶聊天'));
    await tester.pumpAndSettle();

    expect(repository.actions, ['group-pin:dev']);
    expect(refreshCount, 1);
  });

  testWidgets('message list group row mirrors Android pin and follow state', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: Scaffold(
          body: MessageListScreen(
            groups: [
              _fakeGroup.copyWith(isPinned: true, isFollowed: false),
            ],
            items: const [],
          ),
        ),
      ),
    );

    expect(find.byIcon(Icons.push_pin_outlined), findsOneWidget);
    expect(find.text('不再关注'), findsOneWidget);
    final timestamp = tester.widget<Text>(find.text('刚刚'));
    expect(timestamp.style?.fontSize, 11);
  });

  testWidgets('message list dimmed group keeps Android avatar opacity', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: Scaffold(
          body: MessageListScreen(
            groups: [
              _fakeGroup.copyWith(isFollowed: false),
            ],
            items: const [],
          ),
        ),
      ),
    );

    final title = tester.widget<Text>(find.text('超级开发部'));
    expect(title.style?.color, AppTheme.textSecondary);
    expect(
      find.byWidgetPredicate(
        (widget) => widget is Opacity && widget.opacity == 0.52,
      ),
      findsNothing,
    );
  });

  testWidgets('message list dimmed conversation keeps Android avatar opacity', (
    WidgetTester tester,
  ) async {
    const dimmedConversation = ConversationItem(
      id: 'employee:demo:unfollowed',
      type: ConversationType.aiTask,
      title: '不关注员工',
      subtitle: '头像仍保持原色',
      timestampText: '刚刚',
      isFollowed: false,
    );

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: const Scaffold(
          body: MessageListScreen(items: [dimmedConversation]),
        ),
      ),
    );

    final title = tester.widget<Text>(find.text('不关注员工'));
    expect(title.style?.color, AppTheme.textSecondary);
    expect(
      tester.getSize(
        find.byKey(
          const ValueKey(
            'conversation_avatar_stack_employee:demo:unfollowed',
          ),
        ),
      ),
      const Size(52, 52),
    );
    expect(
      find.byWidgetPredicate(
        (widget) => widget is Opacity && widget.opacity == 0.52,
      ),
      findsNothing,
    );
  });

  testWidgets('message list read conversation text colors mirror Android', (
    WidgetTester tester,
  ) async {
    const readConversation = ConversationItem(
      id: 'employee:demo:read',
      type: ConversationType.aiTask,
      title: '已读员工',
      subtitle: '已读预览更接近 Android N600',
      timestampText: '6/24',
    );

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: const Scaffold(
          body: MessageListScreen(items: [readConversation]),
        ),
      ),
    );

    expect(tester.widget<Text>(find.text('6/24')).style?.color,
        AppTheme.textSecondary);
    expect(
      tester.widget<Text>(find.text('已读预览更接近 Android N600')).style?.color,
      AppTheme.textStrongSecondary,
    );
  });

  testWidgets('message list status badge uses Android conversation badge color',
      (
    WidgetTester tester,
  ) async {
    const adminBadge = Color(0xFFED7B2F);
    const conversation = ConversationItem(
      id: 'employee:demo:admin',
      type: ConversationType.aiTask,
      title: '管理端员工',
      subtitle: '徽标颜色来自会话数据',
      timestampText: '6/24',
      badgeText: '管理端',
      badgeColor: 0xFFED7B2F,
    );

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: const Scaffold(
          body: MessageListScreen(items: [conversation]),
        ),
      ),
    );

    final badge = tester.widget<Container>(
      find.byKey(const ValueKey('conversation_status_badge_管理端')),
    );
    final decoration = badge.decoration! as BoxDecoration;
    final border = decoration.border! as Border;
    final label = tester.widget<Text>(find.text('管理端'));

    expect(decoration.color, adminBadge.withValues(alpha: 0.12));
    expect(border.top.color, adminBadge.withValues(alpha: 0.30));
    expect(label.style?.color, adminBadge);
  });

  testWidgets('message list unread conversation text colors mirror Android', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: const Scaffold(
          body: MessageListScreen(items: [_fakeUnreadConversation]),
        ),
      ),
    );

    expect(
      tester.widget<Text>(find.text('刚刚')).style?.color,
      AppTheme.textStrongSecondary,
    );
    expect(
      tester.widget<Text>(find.text('需要跟进')).style?.color,
      AppTheme.textSecondary,
    );
  });

  testWidgets('message list avatar geometry follows Android overflow policy', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: const Scaffold(
          body: MessageListScreen(items: [_fakeUnreadConversation]),
        ),
      ),
    );

    expect(
      tester.getSize(
        find.byKey(
          const ValueKey(
            'conversation_avatar_stack_employee:demo:customer',
          ),
        ),
      ),
      const Size(52, 52),
    );
  });

  testWidgets('group grid avatar follows Android centered grid geometry', (
    WidgetTester tester,
  ) async {
    const members = [
      AiGroupMember(
        employeeId: 'member-1',
        name: '成员1',
        summary: '',
      ),
      AiGroupMember(
        employeeId: 'member-2',
        name: '成员2',
        summary: '',
      ),
      AiGroupMember(
        employeeId: 'member-3',
        name: '成员3',
        summary: '',
      ),
      AiGroupMember(
        employeeId: 'member-4',
        name: '成员4',
        summary: '',
      ),
      AiGroupMember(
        employeeId: 'member-5',
        name: '成员5',
        summary: '',
      ),
    ];

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: Scaffold(
          body: MessageListScreen(
            groups: [
              _fakeGroup.copyWith(memberCount: 5, members: members),
            ],
            items: const [],
          ),
        ),
      ),
    );

    final gridTop = tester.getTopLeft(find.byType(GroupGridAvatar)).dy;
    final fifthTop = tester
        .getTopLeft(find.byKey(const ValueKey('group_avatar_cell_member-5')))
        .dy;

    final firstTop = tester
        .getTopLeft(find.byKey(const ValueKey('group_avatar_cell_member-1')))
        .dy;
    final firstSize = tester.getSize(
      find.byKey(const ValueKey('group_avatar_cell_member-1')),
    );

    expect(firstTop - gridTop, moreOrLessEquals(9.92, epsilon: 0.5));
    expect(fifthTop - gridTop, moreOrLessEquals(26.75, epsilon: 0.5));
    expect(firstSize.width, moreOrLessEquals(15.33, epsilon: 0.02));
    expect(firstSize.height, moreOrLessEquals(15.33, epsilon: 0.02));
  });

  testWidgets('message list group search follows Android name-only filter', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: const Scaffold(
          body: MessageListScreen(
            groups: [_fakeGroup],
            items: [],
          ),
        ),
      ),
    );

    await tester.enterText(find.byType(TextField), '最合适');
    await tester.pumpAndSettle();

    expect(find.text('超级开发部'), findsNothing);

    await tester.enterText(find.byType(TextField), '开发');
    await tester.pump();

    expect(find.text('超级开发部'), findsOneWidget);
  });

  testWidgets('message list empty state mirrors Android ecosystem sync hint', (
    WidgetTester tester,
  ) async {
    var refreshCount = 0;

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: Scaffold(
          body: MessageListScreen(
            items: const [],
            onRefresh: () async {
              refreshCount += 1;
            },
          ),
        ),
      ),
    );

    expect(find.text('账号生态待同步'), findsOneWidget);
    expect(find.text('点这里重新同步管理端员工。'), findsOneWidget);
    expect(find.text('暂无会话'), findsOneWidget);
    expect(find.text('下拉刷新或和小C助理聊聊吧'), findsOneWidget);

    await tester.tap(find.text('账号生态待同步'));
    await tester.pump();

    expect(refreshCount, 1);
  });

  testWidgets('message list loading empty state uses Android wording', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: const Scaffold(
          body: MessageListScreen(
            items: [],
            loading: true,
          ),
        ),
      ),
    );

    expect(find.text('账号生态待同步'), findsOneWidget);
    expect(find.text('正在同步会话…'), findsOneWidget);
    expect(find.byType(CircularProgressIndicator), findsOneWidget);
    expect(find.text('暂无会话'), findsNothing);
  });

  testWidgets('message list header counts only loaded Android AI rows', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: const Scaffold(
          body: MessageListScreen(items: []),
        ),
      ),
    );

    expect(find.text('管理员账号'), findsOneWidget);
    expect(find.textContaining('55位AI员工'), findsNothing);
  });

  testWidgets('bottom nav labels match Android current shell', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: Scaffold(
          bottomNavigationBar: WeBottomNavBar(
            currentIndex: 0,
            onSelect: (_) {},
          ),
        ),
      ),
    );

    expect(find.text('消息'), findsOneWidget);
    expect(find.text('AI员工'), findsOneWidget);
    expect(find.text('探索'), findsOneWidget);
    expect(find.text('我'), findsOneWidget);

    final selectedLabel = tester.widget<Text>(find.text('消息'));
    final unselectedLabel = tester.widget<Text>(find.text('AI员工'));
    expect(selectedLabel.style?.color, AppTheme.brand);
    expect(unselectedLabel.style?.color, AppTheme.textStrongSecondary);
  });

  testWidgets('bottom nav follows Android dark label tokens', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        darkTheme: AppTheme.dark(),
        themeMode: ThemeMode.dark,
        home: Scaffold(
          bottomNavigationBar: WeBottomNavBar(
            currentIndex: 0,
            onSelect: (_) {},
          ),
        ),
      ),
    );

    final colors = AppTheme.colors(
      tester.element(find.byKey(const ValueKey('bottom_nav_tile_消息'))),
    );
    final selectedLabel = tester.widget<Text>(find.text('消息'));
    final unselectedLabel = tester.widget<Text>(find.text('AI员工'));

    expect(selectedLabel.style?.color, colors.brand);
    expect(unselectedLabel.style?.color, colors.textStrongSecondary);
  });

  testWidgets('bottom nav host uses Android scaffold page behind chrome', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: Scaffold(
          bottomNavigationBar: WeBottomNavBar(
            currentIndex: 0,
            onSelect: (_) {},
          ),
        ),
      ),
    );

    final host = tester.widget<ColoredBox>(
      find.byKey(const ValueKey('bottom_nav_surface_host')),
    );
    final safeArea = tester.widget<SafeArea>(
      find.descendant(
        of: find.byKey(const ValueKey('bottom_nav_surface_host')),
        matching: find.byType(SafeArea),
      ),
    );
    final capsule = tester.widget<Material>(
      find.byKey(const ValueKey('bottom_nav_capsule')),
    );

    expect(host.color, AppTheme.page);
    expect(safeArea.minimum, const EdgeInsets.fromLTRB(20, 6, 20, 10));
    expect(capsule.elevation, 8);
  });

  testWidgets('bottom nav hit area fills Android 66dp item surface', (
    WidgetTester tester,
  ) async {
    var selectedIndex = 0;
    tester.view.devicePixelRatio = 1;
    tester.view.physicalSize = const Size(430, 1800);
    addTearDown(tester.view.resetDevicePixelRatio);
    addTearDown(tester.view.resetPhysicalSize);

    await tester.pumpWidget(
      StatefulBuilder(
        builder: (context, setState) {
          return MaterialApp(
            theme: AppTheme.light(),
            home: Scaffold(
              body: const SizedBox.shrink(),
              bottomNavigationBar: WeBottomNavBar(
                currentIndex: selectedIndex,
                onSelect: (index) => setState(() => selectedIndex = index),
              ),
            ),
          );
        },
      ),
    );

    final profileHitRect = bottomNavHitRectForTest(
      screenSize: tester.view.physicalSize,
      viewPadding: EdgeInsets.zero,
      itemIndex: 3,
    );
    await tester.tapAt(
      Offset(profileHitRect.center.dx, profileHitRect.bottom - 2),
    );
    await tester.pumpAndSettle();

    expect(selectedIndex, 3);
  });

  testWidgets('WeTopBar uses Android 64dp default content height', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: const Scaffold(
          body: WeTopBar(title: '小C助理', showBack: true),
        ),
      ),
    );

    expect(
      tester.getSize(find.byKey(const ValueKey('we_top_bar_surface_小C助理'))),
      const Size(800, 64),
    );
  });

  testWidgets('shared mobile chrome follows Android dark theme tokens', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        darkTheme: AppTheme.dark(),
        themeMode: ThemeMode.dark,
        home: Scaffold(
          body: const WeTopBar(title: '小C助理', showBack: true),
          bottomNavigationBar: WeBottomNavBar(
            currentIndex: 0,
            onSelect: (_) {},
          ),
        ),
      ),
    );

    final colors = AppTheme.colors(
      tester.element(find.byKey(const ValueKey('we_top_bar_surface_小C助理'))),
    );
    final topBar = tester.widget<Container>(
      find.byKey(const ValueKey('we_top_bar_surface_小C助理')),
    );
    final bottomTile = tester.widget<Material>(
      find.byKey(const ValueKey('bottom_nav_tile_消息')),
    );

    expect(colors.surface, const Color(0xFF242424));
    expect(topBar.color, colors.surface);
    expect(bottomTile.color, colors.page);
  });

  testWidgets('WeField follows Android dark input background token', (
    WidgetTester tester,
  ) async {
    final controller = TextEditingController();
    addTearDown(controller.dispose);

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        darkTheme: AppTheme.dark(),
        themeMode: ThemeMode.dark,
        home: Scaffold(
          body: WeField(
            controller: controller,
            placeholder: '输入消息',
          ),
        ),
      ),
    );

    final colors = AppTheme.colors(
      tester.element(find.byKey(const ValueKey('we_field_container_输入消息'))),
    );
    final field = tester.widget<Container>(
      find.byKey(const ValueKey('we_field_container_输入消息')),
    );
    final decoration = field.decoration! as BoxDecoration;

    expect(decoration.color, colors.weChatInputBg);
    expect(decoration.color, isNot(colors.page));
  });

  testWidgets('shared We UI text styles use Android typography tokens', (
    WidgetTester tester,
  ) async {
    final controller = TextEditingController();
    addTearDown(controller.dispose);

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: Scaffold(
          body: Column(
            children: [
              const WeTopBar(title: '拓扑'),
              const WeSectionCaption('分组标题'),
              const WeCell(
                title: '单元标题',
                subtitle: '单元副标题',
                value: '右值',
                icon: Icons.settings,
              ),
              WeField(controller: controller, placeholder: '输入内容'),
              WeBlockButton(text: '主按钮', onPressed: () {}),
            ],
          ),
        ),
      ),
    );

    final context = tester.element(find.byType(Scaffold));
    final textTheme = Theme.of(context).textTheme;
    final topTitle = tester.widget<Text>(find.text('拓扑'));
    final caption = tester.widget<Text>(find.text('分组标题'));
    final cellTitle = tester.widget<Text>(find.text('单元标题'));
    final cellSubtitle = tester.widget<Text>(find.text('单元副标题'));
    final cellValue = tester.widget<Text>(find.text('右值'));
    final field = tester.widget<TextField>(find.byType(TextField));
    final button = tester.widget<FilledButton>(find.byType(FilledButton));
    final buttonStyle = button.style!.textStyle!.resolve({});

    expect(topTitle.style?.fontSize, textTheme.titleMedium?.fontSize);
    expect(topTitle.style?.height, textTheme.titleMedium?.height);
    expect(caption.style?.fontSize, textTheme.labelSmall?.fontSize);
    expect(caption.style?.height, textTheme.labelSmall?.height);
    expect(cellTitle.style?.fontSize, textTheme.bodyLarge?.fontSize);
    expect(cellTitle.style?.height, textTheme.bodyLarge?.height);
    expect(cellSubtitle.style?.fontSize, textTheme.bodySmall?.fontSize);
    expect(cellSubtitle.style?.height, textTheme.bodySmall?.height);
    expect(cellValue.style?.fontSize, textTheme.bodyMedium?.fontSize);
    expect(cellValue.style?.height, textTheme.bodyMedium?.height);
    expect(field.style?.fontSize, textTheme.bodyLarge?.fontSize);
    expect(
        field.decoration?.hintStyle?.fontSize, textTheme.bodyLarge?.fontSize);
    expect(buttonStyle?.fontSize, textTheme.bodyLarge?.fontSize);
    expect(buttonStyle?.height, textTheme.bodyLarge?.height);
  });

  testWidgets('chat detail uses Android compact 48dp top bar', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: ChatScreen(
          conversation: demoConversations.first,
          initialMessages: const [],
        ),
      ),
    );

    expect(
      tester.getSize(find.byKey(const ValueKey('we_top_bar_surface_小C助理'))),
      const Size(800, 48),
    );
  });

  testWidgets('chat detail follows Android dark theme tokens', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        darkTheme: AppTheme.dark(),
        themeMode: ThemeMode.dark,
        home: ChatScreen(
          conversation: demoConversations[1],
          initialMessages: const [
            ChatMessage(
              id: 'dark-user',
              conversationId: 'pinned:codex',
              role: ChatRole.user,
              body: '继续',
              timeText: '05:45',
            ),
            ChatMessage(
              id: 'dark-assistant',
              conversationId: 'pinned:codex',
              role: ChatRole.assistant,
              body: '收到',
              timeText: '05:46',
            ),
          ],
        ),
      ),
    );

    final colors = AppTheme.colors(tester.element(find.byType(ChatScreen)));
    final scaffold = tester.widget<Scaffold>(find.byType(Scaffold));
    final composer = tester.widget<Container>(
      find.byKey(const ValueKey('chat_composer_surface')),
    );
    final userBubble = tester.widget<Material>(
      find.byKey(const ValueKey('chat_bubble_dark-user')),
    );
    final assistantBubble = tester.widget<Material>(
      find.byKey(const ValueKey('chat_bubble_dark-assistant')),
    );
    final moreButton = tester.widget<IconButton>(
      find.ancestor(
        of: find.byTooltip('更多'),
        matching: find.byType(IconButton),
      ),
    );

    expect(scaffold.backgroundColor, colors.page);
    expect((composer.decoration as BoxDecoration).color, colors.surface);
    expect(userBubble.color, colors.chatUserBubble);
    expect(assistantBubble.color, colors.surface);
    expect(moreButton.color, colors.textPrimary);
  });

  testWidgets('home shell follows Android conversation list with group rows',
      (WidgetTester tester) async {
    tester.view.devicePixelRatio = 1;
    tester.view.physicalSize = const Size(430, 1800);
    addTearDown(tester.view.resetDevicePixelRatio);
    addTearDown(tester.view.resetPhysicalSize);

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: HomeShell(
          repository: _FakeHomeShellRepository(
            groups: const [_fakeGroup],
            client: _FakeProfileApi(
              session: const MobileSessionData(accountKind: 'admin'),
            ),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    final colors = AppTheme.colors(tester.element(find.byType(HomeShell)));
    final scaffold = tester.widget<Scaffold>(find.byType(Scaffold));
    expect(scaffold.backgroundColor, colors.page);
    expect(find.text('超级开发部'), findsOneWidget);
    expect(find.text('P-W 网站部'), findsNothing);
    expect(find.text('小C助理'), findsWidgets);
    expect(find.text('超级员工-Codex'), findsWidgets);
    expect(
      tester.getTopLeft(find.text('超级开发部')).dy,
      lessThan(tester.getTopLeft(find.text('小C助理').first).dy),
    );
  });

  testWidgets('home shell uses Android personal conversation runtime', (
    WidgetTester tester,
  ) async {
    AndroidProductSkuConfig.setRemoteSku('personal');
    final api = _FakeProfileApi(
      session: const MobileSessionData(accountKind: 'personal'),
    );
    final repository = _FakeHomeShellRepository(client: api);

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: HomeShell(repository: repository),
      ),
    );
    await tester.pumpAndSettle();

    expect(repository.conversationLoads.last, {
      'adminMode': false,
      'enterpriseMode': false,
    });
    expect(find.text('小C助理'), findsWidgets);
    expect(find.text('超级员工-Codex'), findsNothing);
    expect(find.text('专属客服'), findsNothing);
    expect(find.text('客户客服'), findsNothing);
  });

  testWidgets('home shell treats Android admin as enterprise effective', (
    WidgetTester tester,
  ) async {
    AndroidProductSkuConfig.setRemoteSku('personal');
    final api = _FakeProfileApi(
      session: const MobileSessionData(accountKind: 'admin_portal'),
    );
    final repository = _FakeHomeShellRepository(client: api);

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: HomeShell(repository: repository),
      ),
    );
    await tester.pumpAndSettle();

    expect(repository.conversationLoads.last, {
      'adminMode': true,
      'enterpriseMode': true,
    });
    expect(find.text('超级员工-Codex'), findsWidgets);
    expect(find.text('专属客服'), findsNothing);
    expect(find.text('客户客服'), findsWidgets);
    expect(find.text('查看并回复企业客户的客服消息'), findsWidgets);

    await tester.tap(find.text('客户客服').first);
    await tester.pumpAndSettle();

    expect(find.byType(BridgeScreen), findsOneWidget);
    expect(repository.bridgeRequestTypes, [
      MobileRepository.customerServiceRequestType,
    ]);
    expect(find.text('客户客服'), findsOneWidget);
    expect(find.text('客户消息'), findsOneWidget);
    expect(find.text('手机端客户'), findsWidgets);
    expect(find.byType(CsChatScreen), findsNothing);
    expect(find.byType(ChatScreen), findsNothing);
  });

  testWidgets('home shell hides Android bottom nav on pushed direct chat', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: HomeShell(repository: _FakeHomeShellRepository()),
      ),
    );
    await tester.pumpAndSettle();

    await tester.tap(find.text('小C助理').first);
    await tester.pumpAndSettle();

    expect(find.text('发消息'), findsOneWidget);
    expect(find.text('消息'), findsNothing);
    expect(find.text('AI员工'), findsNothing);
    expect(find.text('探索'), findsNothing);
    expect(find.text('我'), findsNothing);
  });

  testWidgets('home shell shares repository with AI employee tab', (
    WidgetTester tester,
  ) async {
    final repository = _FakeHomeShellRepository(
      employees: adminDutyEmployeeProfiles(const [
        DutyRosterEmployee(
          id: 'home-shell-employee',
          label: '同源仓库员工',
          summary: '来自 HomeShell 注入的 repository',
        ),
      ]),
    );

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: HomeShell(repository: repository),
      ),
    );
    await tester.pumpAndSettle();

    await tester.tap(find.text('AI员工'));
    await tester.pumpAndSettle();

    expect(repository.employeeLoads, 1);
    expect(find.text('同源仓库员工'), findsOneWidget);
    expect(find.textContaining('AI号 home-shell-employee'), findsOneWidget);
  });

  testWidgets('home shell shares repository API with profile tab', (
    WidgetTester tester,
  ) async {
    final api = _FakeProfileApi(
      profilePage: const MobileProfilePageConfig(
        enabled: true,
        revision: 'home-shell',
        heroVariant: 'glass',
        headline: '同源 Profile 配置',
        subtitle: '来自 HomeShell repository client',
        statusReady: '同源状态已就绪',
        statusSyncing: '',
        primaryChip: '管理员账号',
        secondaryChip: '服务器中继 · 电脑执行端',
        accent: 'indigo',
      ),
    );
    final repository = _FakeHomeShellRepository(client: api);

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: HomeShell(repository: repository),
      ),
    );
    await tester.pumpAndSettle();

    expect(api.walletLoads, greaterThan(0));
    expect(api.appConfigLoads, greaterThan(0));

    await tester.tap(find.text('我'));
    await tester.pumpAndSettle();

    expect(find.text('同源 Profile 配置'), findsOneWidget);
    expect(find.text('来自 HomeShell repository client'), findsOneWidget);
  });

  testWidgets('home shell refreshes Android local profile after profile edit', (
    WidgetTester tester,
  ) async {
    final api = _FakeProfileApi(
      session: const MobileSessionData(
        username: 'admin',
        accountKind: 'admin',
      ),
    );
    final repository = _FakeHomeShellRepository(
      client: api,
      accountFromClientSession: true,
    );

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: HomeShell(repository: repository),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('admin'), findsWidgets);

    await tester.tap(find.text('我'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('个人资料与工作身份'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField).last, 'admin-local');
    await tester.pump();
    await tester.tap(find.text('保存'));
    await tester.pumpAndSettle();

    await tester.tap(find.text('消息'));
    await tester.pumpAndSettle();

    expect(find.text('admin-local'), findsOneWidget);
    expect(api.session.username, 'admin-local');
  });

  testWidgets('home shell seeds Android cached avatar before network refresh', (
    WidgetTester tester,
  ) async {
    final api = _FakeProfileApi(
      session: const MobileSessionData(
        username: 'admin',
        accountKind: 'admin',
        userId: 1,
        localAvatarSource: '/tmp/android-local-avatar.jpg',
      ),
    );
    final repository = _SlowMeHomeShellRepository(client: api);

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: HomeShell(repository: repository),
      ),
    );
    await tester.pump();
    await tester.pump();

    final headerAvatar = tester.widget<AppAvatar>(find.byType(AppAvatar).first);
    expect(headerAvatar.imageSource, '/tmp/android-local-avatar.jpg');
    expect(repository.loadMeCalls, 1);
  });

  testWidgets('home shell renders Android cached employees before refresh', (
    WidgetTester tester,
  ) async {
    final repository = _CachedFirstHomeShellRepository();

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: HomeShell(repository: repository),
      ),
    );
    await tester.pump();
    await tester.pump();
    await tester.drag(find.byType(ListView).first, const Offset(0, -520));
    await tester.pump();

    expect(find.text('缓存头像员工'), findsOneWidget);
    expect(find.text('我: 先看缓存'), findsOneWidget);
    expect(repository.loadConversationCalls, 1);
    expect(repository.remoteConversations.isCompleted, isFalse);
  });

  testWidgets('home shell keeps Android cached employees after refresh failure',
      (
    WidgetTester tester,
  ) async {
    final repository = _CachedFirstHomeShellRepository();

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: HomeShell(repository: repository),
      ),
    );
    await tester.pump();
    await tester.pump();

    repository.remoteConversations.completeError(
      const MobileRepositoryException('offline'),
    );
    await tester.pump();
    await tester.pump();
    await tester.drag(find.byType(ListView).first, const Offset(0, -520));
    await tester.pump();

    expect(find.text('缓存头像员工'), findsOneWidget);
    expect(find.text('我: 先看缓存'), findsOneWidget);
    expect(find.text('账号生态待同步'), findsNothing);
    expect(repository.loadConversationCalls, 1);
  });

  testWidgets('home shell header uses Android me endpoint account data', (
    WidgetTester tester,
  ) async {
    final repository = _FakeHomeShellRepository(
      client: _FakeProfileApi(
        session: const MobileSessionData(accountKind: 'admin'),
      ),
      account: const MobileMeData(
        user: MobileUserData(
          id: 7,
          username: 'fallback-name',
          displayName: '真实账号',
          email: '',
          role: 'admin',
          isActive: true,
          avatarUrl: null,
        ),
        permissions: [],
        accountKind: 'enterprise',
        companyBrand: '',
        modIds: [],
      ),
    );

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: HomeShell(repository: repository),
      ),
    );
    await tester.pumpAndSettle();

    expect(repository.accountLoads, 1);
    expect(find.text('fallback-name'), findsOneWidget);
    expect(find.text('企业账号 · 55位AI员工'), findsOneWidget);
    expect(find.text('admin'), findsNothing);
  });

  testWidgets('AI employees tab matches Android employee roster shell', (
    WidgetTester tester,
  ) async {
    tester.view.devicePixelRatio = 1;
    tester.view.physicalSize = const Size(430, 1800);
    addTearDown(tester.view.resetDevicePixelRatio);
    addTearDown(tester.view.resetPhysicalSize);

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: Scaffold(
          body: AiEmployeesScreen(
            repository: _FakeEmployeesRepository(adminDutyEmployeeProfiles()),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('AI员工(55)'), findsOneWidget);
    final aiEmployeeTitle = tester.widget<Text>(
      find.byKey(const ValueKey('ai_employee_title')),
    );
    expect(aiEmployeeTitle.style?.fontSize, 18);
    expect(aiEmployeeTitle.style?.fontWeight, FontWeight.w600);
    expect(find.text('查找会话或伙伴'), findsOneWidget);
    expect(
      tester.getSize(find.byKey(const ValueKey('ai_employee_search_bar'))),
      const Size(406, 38),
    );
    expect(find.text('静态站内容编辑员'), findsOneWidget);
    expect(find.text('SEO 站点地图管理员'), findsOneWidget);
    expect(find.textContaining('AI号 site-content-editor'), findsOneWidget);

    await tester.tap(find.text('静态站内容编辑员'));
    await tester.pumpAndSettle();

    expect(find.text('员工资料'), findsOneWidget);
    expect(find.text('AI交流圈'), findsOneWidget);
    expect(find.text('发消息'), findsOneWidget);
  });

  testWidgets('AI employees tab follows Android dark theme tokens', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        darkTheme: AppTheme.dark(),
        themeMode: ThemeMode.dark,
        home: AiEmployeesScreen(
          repository: _FakeEmployeesRepository(adminDutyEmployeeProfiles()),
        ),
      ),
    );
    await tester.pumpAndSettle();

    final colors =
        AppTheme.colors(tester.element(find.byType(AiEmployeesScreen)));
    final scaffold = tester.widget<Scaffold>(find.byType(Scaffold).first);
    expect(scaffold.backgroundColor, colors.page);

    final aiEmployeeTitle = tester.widget<Text>(
      find.byKey(const ValueKey('ai_employee_title')),
    );
    expect(aiEmployeeTitle.style?.color, colors.textPrimary);

    final searchBar = tester.widget<Container>(
      find.byKey(const ValueKey('ai_employee_search_bar')),
    );
    final decoration = searchBar.decoration as BoxDecoration;
    expect(decoration.color, colors.surfaceHigh);
    expect(decoration.border, isA<Border>());
    final border = decoration.border! as Border;
    expect(border.top.color, colors.divider);
  });

  testWidgets('AI employee profile source mirrors Android source label', (
    WidgetTester tester,
  ) async {
    const employee = AiEmployeeProfile(
      modId: 'avatar-mod',
      modName: '头像员工包',
      modDescription: '生成头像',
      modVersion: '1.0.0',
      modAuthor: 'XCAGI',
      industryName: '视觉',
      employeeId: 'avatar-generation-employee',
      name: '头像生成员工',
      title: '头像设计师',
      summary: '从市场同步的头像生成资料',
      apiBasePath: '/api/avatar',
      phoneChannel: 'mobile-chat',
      workflowPlaceholder: false,
      profileSource: 'market',
      marketConnected: true,
      marketPkgId: 'avatar-generation-employee',
      marketVersion: '1.0.0',
      marketAuthor: 'XCAGI',
      marketMaterialCategory: 'AI 员工',
      marketLicenseScope: 'enterprise',
      marketSecurityLevel: 'standard',
    );

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: const AiEmployeeProfileScreen(employee: employee),
      ),
    );

    expect(find.text('来源：AI市场 · 头像员工包'), findsOneWidget);
    expect(find.text('AI市场 · 头像员工包'), findsOneWidget);
    expect(find.text('管理端 AI 员工'), findsNothing);
    expect(
      find.byWidgetPredicate(
        (widget) =>
            widget is Icon &&
            widget.icon == Icons.forum &&
            widget.color == AppTheme.momentAccent,
      ),
      findsOneWidget,
    );
  });

  testWidgets('AI employee profile reloads Android current employee source', (
    WidgetTester tester,
  ) async {
    const staleEmployee = AiEmployeeProfile(
      modId: 'avatar-mod',
      modName: '头像员工包',
      modDescription: '生成头像',
      modVersion: '1.0.0',
      modAuthor: 'XCAGI',
      industryName: '视觉',
      employeeId: 'avatar-generation-employee',
      name: '头像生成员工',
      title: '旧昵称',
      summary: '旧员工资料',
      apiBasePath: '/api/avatar',
      phoneChannel: 'mobile-chat',
      workflowPlaceholder: false,
      profileSource: 'market',
      marketConnected: true,
      marketPkgId: 'avatar-generation-employee',
      marketVersion: '1.0.0',
      marketAuthor: 'XCAGI',
      marketMaterialCategory: 'AI 员工',
      marketLicenseScope: 'enterprise',
      marketSecurityLevel: 'standard',
    );
    const currentEmployee = AiEmployeeProfile(
      modId: 'avatar-mod',
      modName: '头像员工包',
      modDescription: '生成头像',
      modVersion: '1.0.1',
      modAuthor: 'XCAGI',
      industryName: '视觉',
      employeeId: 'avatar-generation-employee',
      name: '头像生成员工',
      title: '当前昵称',
      summary: '当前员工资料',
      apiBasePath: '/api/avatar',
      phoneChannel: 'mobile-chat',
      workflowPlaceholder: false,
      profileSource: 'market',
      marketConnected: true,
      marketPkgId: 'avatar-generation-employee',
      marketVersion: '1.0.1',
      marketAuthor: 'XCAGI',
      marketMaterialCategory: 'AI 员工',
      marketLicenseScope: 'enterprise',
      marketSecurityLevel: 'standard',
    );
    final repository = _FakeEmployeesRepository(const [currentEmployee]);

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: AiEmployeeProfileScreen(
          employee: staleEmployee,
          repository: repository,
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(repository.employeeLoads, 1);
    expect(find.text('昵称：当前昵称'), findsOneWidget);
    expect(find.text('当前员工资料'), findsOneWidget);
    expect(find.text('旧员工资料'), findsNothing);
  });

  testWidgets(
      'AI employee profile not found state mirrors Android refresh empty',
      (WidgetTester tester) async {
    final employee = adminDutyEmployeeProfiles().first;
    final repository = _FakeEmployeesRepository(const []);

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: AiEmployeeProfileScreen(
          employee: employee,
          repository: repository,
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('未找到该 AI 员工'), findsOneWidget);
    expect(find.text('稍后刷新或从企业端同步数据'), findsOneWidget);
    expect(find.text('刷新'), findsOneWidget);
    expect(repository.employeeLoads, 1);

    await tester.tap(find.text('刷新'));
    await tester.pumpAndSettle();

    expect(repository.employeeLoads, 2);
  });

  testWidgets('AI employee profile follows Android dark theme tokens', (
    WidgetTester tester,
  ) async {
    final employee = adminDutyEmployeeProfiles().first;
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        darkTheme: AppTheme.dark(),
        themeMode: ThemeMode.dark,
        home: AiEmployeeProfileScreen(employee: employee),
      ),
    );

    final colors =
        AppTheme.colors(tester.element(find.byType(AiEmployeeProfileScreen)));
    final scaffold = tester.widget<Scaffold>(find.byType(Scaffold).first);
    expect(scaffold.backgroundColor, colors.page);

    final nameText = tester.widget<Text>(find.text(employee.name).first);
    expect(nameText.style?.color, colors.textPrimary);

    final sourceText =
        tester.widget<Text>(find.text('来源：${employee.sourceLabel}').first);
    expect(sourceText.style?.color, colors.textSecondary);

    await tester.scrollUntilVisible(find.text('发消息'), 240);
    final chatText = tester.widget<Text>(find.text('发消息').first);
    expect(chatText.style?.color, colors.brand);
  });

  testWidgets('AI employees empty state matches Android bind prompt', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: Scaffold(
          body: AiEmployeesScreen(
            repository: _FakeEmployeesRepository(const []),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('查找会话或伙伴'), findsNothing);
    expect(find.text('暂无 AI 员工'), findsOneWidget);
    expect(find.text('扫码绑定企业端或登录管理端后，员工会自动同步到这里。'), findsOneWidget);
    expect(find.text('扫码绑定'), findsWidgets);
    expect(find.byIcon(Icons.auto_awesome), findsOneWidget);
  });

  testWidgets('AI employees search empty state matches Android wording', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: Scaffold(
          body: AiEmployeesScreen(
            repository: _FakeEmployeesRepository(adminDutyEmployeeProfiles()),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    await tester.enterText(find.byType(TextField), 'no-such-employee');
    await tester.pumpAndSettle();

    expect(find.text('未找到匹配的 AI 员工'), findsOneWidget);
    expect(find.text('扫码绑定企业端或登录管理端后，员工会自动同步到这里。'), findsNothing);
  });

  testWidgets('discover tab matches Android tool sections', (
    WidgetTester tester,
  ) async {
    tester.view.devicePixelRatio = 1;
    tester.view.physicalSize = const Size(430, 1800);
    addTearDown(tester.view.resetDevicePixelRatio);
    addTearDown(tester.view.resetPhysicalSize);

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: const Scaffold(body: DiscoverScreen()),
      ),
    );

    expect(find.text('探索'), findsOneWidget);
    expect(
      find.byKey(const ValueKey('we_top_bar_divider_探索')),
      findsOneWidget,
    );
    expect(find.text('AI交流'), findsOneWidget);
    expect(find.text('AI交流圈'), findsOneWidget);
    expect(find.text('桌面工具（与电脑端侧栏对齐）'), findsOneWidget);
    expect(find.text('扫码绑定电脑端'), findsOneWidget);
    expect(find.text('绑定后，电脑端侧栏的工具会同步到这里'), findsOneWidget);
    expect(
      tester
          .widget<Icon>(find.byKey(const ValueKey('we_cell_icon_AI交流圈')))
          .color,
      AppTheme.brand,
    );
    expect(
      (tester
              .widget<Container>(
                find.byKey(const ValueKey('we_cell_icon_box_AI交流圈')),
              )
              .decoration! as BoxDecoration)
          .color,
      AppTheme.brandContainer,
    );
    expect(
      tester
          .widget<Icon>(find.byKey(const ValueKey('we_cell_icon_OCR识别')))
          .color,
      AppTheme.light().colorScheme.tertiary,
    );
    expect(
      (tester
              .widget<Container>(
                find.byKey(const ValueKey('we_cell_icon_box_OCR识别')),
              )
              .decoration! as BoxDecoration)
          .color,
      AppTheme.light().colorScheme.tertiaryContainer,
    );
    expect(
      tester
          .widget<Icon>(find.byKey(const ValueKey('we_cell_icon_通知与公告')))
          .color,
      AppTheme.danger,
    );
    expect(
      (tester
              .widget<Container>(
                find.byKey(const ValueKey('we_cell_icon_box_通知与公告')),
              )
              .decoration! as BoxDecoration)
          .color,
      AppTheme.light().colorScheme.errorContainer,
    );
  });

  testWidgets('discover tab follows Android dark theme tokens', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        darkTheme: AppTheme.dark(),
        themeMode: ThemeMode.dark,
        home: const Scaffold(body: DiscoverScreen()),
      ),
    );

    final colors = AppTheme.colors(tester.element(find.byType(DiscoverScreen)));
    final topBar = tester.widget<Container>(
      find.byKey(const ValueKey('we_top_bar_surface_探索')),
    );
    final aiCircleIcon = tester.widget<Icon>(
      find.byKey(const ValueKey('we_cell_icon_AI交流圈')),
    );
    final aiCircleIconBox = tester.widget<Container>(
      find.byKey(const ValueKey('we_cell_icon_box_AI交流圈')),
    );
    final title = tester.widget<Text>(find.text('AI交流圈'));

    expect(
      find.byWidgetPredicate(
        (widget) => widget is ColoredBox && widget.color == colors.surface,
      ),
      findsWidgets,
    );
    expect(topBar.color, colors.surface);
    expect(aiCircleIcon.color, colors.brand);
    expect(
      (aiCircleIconBox.decoration! as BoxDecoration).color,
      colors.brandContainer,
    );
    expect(title.style?.color, colors.textPrimary);
  });

  testWidgets(
      'discover desktop tools follow Android native map and hidden keys', (
    WidgetTester tester,
  ) async {
    var openedWork = 0;

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: Scaffold(
          body: DiscoverScreen(
            repository: _FakeDiscoverRepository(
              const [
                MobileNavMenuItem(
                  key: 'chat',
                  name: '智能对话',
                  icon: 'comment',
                  path: '/chat',
                  source: 'core',
                  modId: null,
                ),
                MobileNavMenuItem(
                  key: 'im',
                  name: 'IM 消息',
                  icon: 'envelope',
                  path: '/im',
                  source: 'core',
                  modId: null,
                ),
                MobileNavMenuItem(
                  key: 'ai-ecosystem',
                  name: 'AI员工生态',
                  icon: 'sitemap',
                  path: '/ai-ecosystem',
                  source: 'core',
                  modId: null,
                ),
                MobileNavMenuItem(
                  key: 'employee-workflow',
                  name: '员工工作流',
                  icon: 'users',
                  path: '/employee-workflow',
                  source: 'core',
                  modId: null,
                ),
                MobileNavMenuItem(
                  key: 'settings',
                  name: '设置入口',
                  icon: 'cog',
                  path: '/settings',
                  source: 'core',
                  modId: null,
                ),
                MobileNavMenuItem(
                  key: 'smart_analysis',
                  name: '智慧分析',
                  icon: 'sparkles',
                  path: '/smart-analysis',
                  source: 'core',
                  modId: null,
                ),
              ],
            ),
            onOpenWork: () => openedWork += 1,
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('智能对话'), findsNothing);
    expect(find.text('IM 消息'), findsNothing);
    expect(find.text('AI员工生态'), findsOneWidget);
    expect(find.text('员工工作流'), findsOneWidget);
    expect(find.text('设置入口'), findsOneWidget);
    expect(find.text('智慧分析'), findsOneWidget);
    expect(find.text('点击打开'), findsWidgets);

    await tester.tap(find.text('AI员工生态'));
    await tester.pumpAndSettle();
    expect(find.text('AI员工(55)'), findsOneWidget);
    await tester.tap(find.byTooltip('返回'));
    await tester.pumpAndSettle();

    await tester.tap(find.text('员工工作流'));
    await tester.pump();
    expect(openedWork, 1);

    await tester.tap(find.text('设置入口'));
    await tester.pumpAndSettle();
    expect(find.text('生物识别解锁'), findsOneWidget);
  });

  testWidgets('AI circle renders Android moments shell from backend data', (
    WidgetTester tester,
  ) async {
    tester.view.devicePixelRatio = 1;
    tester.view.physicalSize = const Size(430, 1800);
    addTearDown(tester.view.resetDevicePixelRatio);
    addTearDown(tester.view.resetPhysicalSize);

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: AiCircleScreen(repository: _FakeCircleRepository()),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('AI交流圈'), findsOneWidget);
    expect(find.text('AI员工交流圈'), findsOneWidget);
    expect(find.text('55 位智能伙伴正在企业账号里值守'), findsOneWidget);
    expect(find.text('企业账号生态'), findsOneWidget);
    expect(find.text('员工动态、能力更新和协同消息会在这里汇总。'), findsOneWidget);
    expect(find.text('静态站内容编辑员'), findsOneWidget);
    expect(find.text('已完成首页内容巡检。'), findsOneWidget);
    expect(find.text('赞'), findsOneWidget);
    expect(find.text('评论'), findsOneWidget);
    expect(find.text('主页'), findsOneWidget);

    final author = tester.widget<Text>(find.text('静态站内容编辑员'));
    expect(author.style?.color, AppTheme.momentAccent);
    final commentAction = tester.widget<Text>(find.text('评论'));
    expect(commentAction.style?.color, AppTheme.momentAccent);
    final homeAction = tester.widget<Text>(find.text('主页'));
    expect(homeAction.style?.color, AppTheme.momentAccent);
    expect(
      find.byWidgetPredicate(
        (widget) =>
            widget is Container &&
            widget.decoration is BoxDecoration &&
            (widget.decoration as BoxDecoration).color == AppTheme.replyBoxBg,
      ),
      findsOneWidget,
    );
  });

  testWidgets('AI circle keeps Android empty employee header without fallback',
      (WidgetTester tester) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: AiCircleScreen(
          repository: _FakeCircleRepository(failEmployees: true),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('0 位智能伙伴正在企业账号里值守'), findsOneWidget);
    expect(find.text('55 位智能伙伴正在企业账号里值守'), findsNothing);
    expect(find.text('已完成首页内容巡检。'), findsOneWidget);
  });

  testWidgets(
      'AI circle like failure uses Android product error and rolls back',
      (WidgetTester tester) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: AiCircleScreen(
          repository: _FakeCircleRepository(failLike: true),
        ),
      ),
    );
    await tester.pumpAndSettle();

    await tester.tap(find.text('赞'));
    await tester.pumpAndSettle();

    expect(find.text('赞'), findsOneWidget);
    expect(find.text('赞 1'), findsNothing);
    expect(find.text('连接不到电脑执行端，已尝试通过服务器中继，请稍后重试'), findsOneWidget);
    expect(find.textContaining('failed to connect'), findsNothing);
  });

  testWidgets('notifications page renders Android announcement list shell', (
    WidgetTester tester,
  ) async {
    tester.view.devicePixelRatio = 1;
    tester.view.physicalSize = const Size(430, 1800);
    addTearDown(tester.view.resetDevicePixelRatio);
    addTearDown(tester.view.resetPhysicalSize);

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: NotificationListScreen(repository: _FakeNotificationRepository()),
      ),
    );
    await tester.pump();

    expect(find.text('通知与公告'), findsOneWidget);
    expect(
      find.byKey(const ValueKey('we_top_bar_divider_通知与公告')),
      findsOneWidget,
    );
    expect(find.text('移动端通知'), findsOneWidget);
    expect(find.text('后台任务已经完成'), findsOneWidget);
    expect(find.byIcon(Icons.info), findsOneWidget);
  });

  testWidgets('notifications page follows Android dark theme tokens', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        darkTheme: AppTheme.dark(),
        themeMode: ThemeMode.dark,
        home: NotificationListScreen(repository: _FakeNotificationRepository()),
      ),
    );
    await tester.pumpAndSettle();

    final colors =
        AppTheme.colors(tester.element(find.byType(NotificationListScreen)));
    final scaffold = tester.widget<Scaffold>(find.byType(Scaffold));
    final topBar = tester.widget<Container>(
      find.byKey(const ValueKey('we_top_bar_surface_通知与公告')),
    );
    final title = tester.widget<Text>(find.text('移动端通知'));
    final systemIcon = tester.widget<Icon>(find.byIcon(Icons.info));

    expect(scaffold.backgroundColor, colors.page);
    expect(topBar.color, colors.surface);
    expect(title.style?.color, colors.textPrimary);
    expect(systemIcon.color, colors.brand);
  });

  testWidgets('OCR page matches Android entry and status sections', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(theme: AppTheme.light(), home: const OcrScreen()),
    );

    expect(find.text('拍照识别'), findsWidgets);
    expect(
      find.byKey(const ValueKey('we_top_bar_divider_拍照识别')),
      findsOneWidget,
    );
    expect(find.text('入口'), findsOneWidget);
    expect(find.text('从相册选择'), findsOneWidget);
    expect(find.text('批量识别'), findsOneWidget);
    expect(find.text('状态'), findsOneWidget);
    expect(find.text('企业 OCR'), findsOneWidget);

    await tester.tap(find.byIcon(Icons.camera_alt));
    await tester.pumpAndSettle();
    expect(find.text('移动端拍照上传正在接入，请先使用电脑端 OCR'), findsOneWidget);
    await tester.pump(const Duration(seconds: 4));
    await tester.pumpAndSettle();
    await tester.tap(find.byIcon(Icons.photo_library));
    await tester.pumpAndSettle();
    expect(find.text('移动端相册识别正在接入，请先使用电脑端 OCR'), findsOneWidget);
  });

  testWidgets('OCR page follows Android dark theme tokens', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        darkTheme: AppTheme.dark(),
        themeMode: ThemeMode.dark,
        home: const OcrScreen(),
      ),
    );

    final colors = AppTheme.colors(tester.element(find.byType(OcrScreen)));
    final scaffold = tester.widget<Scaffold>(find.byType(Scaffold));
    final topBar = tester.widget<Container>(
      find.byKey(const ValueKey('we_top_bar_surface_拍照识别')),
    );
    final cameraIcon = tester.widget<Icon>(
      find.byKey(const ValueKey('we_cell_icon_拍照识别')),
    );
    final albumIcon = tester.widget<Icon>(
      find.byKey(const ValueKey('we_cell_icon_从相册选择')),
    );

    expect(scaffold.backgroundColor, colors.page);
    expect(topBar.color, colors.surface);
    expect(cameraIcon.color, colors.brand);
    expect(albumIcon.color, colors.success);
  });

  testWidgets('scan page renders Android scanner shell and manual code entry', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: const ScanQrScreen(enableCamera: false),
      ),
    );

    expect(find.text('扫一扫'), findsOneWidget);
    expect(find.byIcon(Icons.photo_library), findsOneWidget);
    expect(find.byIcon(Icons.flash_off), findsNothing);
    expect(find.byIcon(Icons.flash_on), findsNothing);
    expect(find.text('输入设备码'), findsOneWidget);
    expect(find.text('将电脑端显示的配对二维码放入框内，即可自动扫描'), findsOneWidget);

    await tester.tap(find.text('输入设备码'));
    await tester.pump(const Duration(milliseconds: 300));

    expect(find.text('请输入电脑端显示的 6 位设备码'), findsOneWidget);
    expect(find.text('连接'), findsOneWidget);
    expect(
        tester.getSize(find.byKey(const ValueKey('we_block_button_连接'))).height,
        44);
    final connectButton = tester.widget<FilledButton>(
      find.descendant(
        of: find.byKey(const ValueKey('we_block_button_连接')),
        matching: find.byType(FilledButton),
      ),
    );
    expect(connectButton.onPressed, isNull);
    expect(
      find.byWidgetPredicate(
        (widget) => widget.runtimeType.toString() == '_PairingDigitBox',
      ),
      findsNWidgets(6),
    );
  });

  testWidgets('scan page follows Android dark theme tokens', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        darkTheme: AppTheme.dark(),
        themeMode: ThemeMode.dark,
        home: const ScanQrScreen(enableCamera: false),
      ),
    );

    final colors = AppTheme.colors(tester.element(find.byType(ScanQrScreen)));
    final manualEntry = tester.widget<Text>(find.text('输入设备码'));
    expect(manualEntry.style?.color, colors.brand);

    await tester.tap(find.text('输入设备码'));
    await tester.pump(const Duration(milliseconds: 300));

    final sheetTitle = tester.widget<Text>(find.text('输入设备码').last);
    final sheetSubtitle = tester.widget<Text>(
      find.text('请输入电脑端显示的 6 位设备码'),
    );

    expect(sheetTitle.style?.color, colors.textPrimary);
    expect(sheetSubtitle.style?.color, colors.textSecondary);
  });

  testWidgets('scan pairing success follows Android full-screen overlay', (
    WidgetTester tester,
  ) async {
    final repository = _FakePairingRepository();

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: ScanQrScreen(
          repository: repository,
          enableCamera: false,
        ),
      ),
    );

    await tester.tap(find.text('输入设备码').last);
    await tester.pump(const Duration(milliseconds: 300));
    await tester.enterText(find.byType(TextField), '123456');
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 100));

    expect(repository.pairingCodes, ['123456']);
    expect(find.byType(AlertDialog), findsNothing);
    expect(find.text('设备绑定成功'), findsNothing);
    expect(find.text('配对成功'), findsOneWidget);
    expect(find.text('手机与电脑已连接'), findsOneWidget);

    await tester.pump(const Duration(milliseconds: 1700));
  });

  testWidgets('scan pairing failure uses Android product error', (
    WidgetTester tester,
  ) async {
    final repository = _FakePairingRepository(failPairing: true);

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: ScanQrScreen(
          repository: repository,
          enableCamera: false,
        ),
      ),
    );

    await tester.tap(find.text('输入设备码').last);
    await tester.pump(const Duration(milliseconds: 300));
    await tester.enterText(find.byType(TextField), '123456');
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 300));

    expect(repository.pairingCodes, ['123456']);
    expect(find.text('连接不到电脑执行端，已尝试通过服务器中继，请稍后重试'), findsOneWidget);
    expect(find.textContaining('failed to connect'), findsNothing);
    expect(find.text('配对成功'), findsNothing);
  });

  testWidgets(
      'settings page matches Android security appearance feedback shell', (
    WidgetTester tester,
  ) async {
    tester.view.devicePixelRatio = 1;
    tester.view.physicalSize = const Size(430, 1800);
    addTearDown(tester.view.resetDevicePixelRatio);
    addTearDown(tester.view.resetPhysicalSize);

    await tester.pumpWidget(
      MaterialApp(theme: AppTheme.light(), home: const SettingsScreen()),
    );

    expect(find.text('设置'), findsOneWidget);
    expect(
      find.byKey(const ValueKey('we_top_bar_divider_设置')),
      findsOneWidget,
    );
    expect(find.text('安全'), findsOneWidget);
    expect(find.text('生物识别解锁'), findsOneWidget);
    expect(
      tester.getSize(find.byKey(const ValueKey('settings_we_switch'))),
      const Size(46, 28),
    );
    expect(find.text('外观'), findsOneWidget);
    expect(find.text('主题模式'), findsOneWidget);
    expect(find.text('跟随'), findsOneWidget);
    expect(find.text('浅色'), findsOneWidget);
    expect(find.text('深色'), findsOneWidget);
    expect(find.text('反馈'), findsOneWidget);
    expect(find.text('问题反馈'), findsOneWidget);
    final colors = AppTheme.colors(tester.element(find.byType(SettingsScreen)));
    final feedbackIconBox = tester.widget<Container>(
      find.byKey(const ValueKey('we_cell_icon_box_问题反馈')),
    );
    final feedbackIconDecoration = feedbackIconBox.decoration! as BoxDecoration;
    expect(
      feedbackIconDecoration.color,
      colors.warning.withValues(alpha: 0.14),
    );
    expect(
      tester
          .getSize(
              find.byKey(const ValueKey('settings_feedback_bottom_spacer')))
          .height,
      XcagiSpacing.md,
    );
    expect(find.text('版本'), findsOneWidget);
    expect(find.text('检查更新'), findsOneWidget);
  });

  testWidgets('settings page follows Android dark theme tokens', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        darkTheme: AppTheme.dark(),
        themeMode: ThemeMode.dark,
        home: const SettingsScreen(),
      ),
    );

    final colors = AppTheme.colors(tester.element(find.byType(SettingsScreen)));
    final scaffold = tester.widget<Scaffold>(find.byType(Scaffold));
    final topBar = tester.widget<Container>(
      find.byKey(const ValueKey('we_top_bar_surface_设置')),
    );
    final switchWidget = tester.widget<AnimatedContainer>(
      find.byKey(const ValueKey('settings_we_switch')),
    );
    final switchDecoration = switchWidget.decoration! as BoxDecoration;
    final themeIcon = tester.widget<Icon>(
      find.byKey(const ValueKey('we_cell_icon_主题模式')),
    );
    final selectedThemeMode = tester.widget<Text>(find.text('跟随').last);
    final scheme =
        Theme.of(tester.element(find.byType(SettingsScreen))).colorScheme;

    expect(scaffold.backgroundColor, colors.surface);
    expect(topBar.color, colors.surface);
    expect(
      switchDecoration.color,
      scheme.outline.withValues(alpha: 0.28),
    );
    expect(themeIcon.color, colors.success);
    expect(selectedThemeMode.style?.color, scheme.onPrimary);
    expect(
      selectedThemeMode.style?.fontSize,
      Theme.of(tester.element(find.byType(SettingsScreen)))
          .textTheme
          .labelMedium
          ?.fontSize,
    );
    expect(
      selectedThemeMode.style?.height,
      Theme.of(tester.element(find.byType(SettingsScreen)))
          .textTheme
          .labelMedium
          ?.height,
    );
  });

  testWidgets('settings persists Android biometric and theme state', (
    WidgetTester tester,
  ) async {
    final api = _FakeSettingsApi(
      session: const MobileSessionData(
        biometricEnabled: true,
        themeMode: 'dark',
      ),
    );

    await tester.pumpWidget(
      MaterialApp(theme: AppTheme.light(), home: SettingsScreen(api: api)),
    );
    await tester.pumpAndSettle();

    expect(find.text('已开启'), findsOneWidget);
    expect(find.text('深色'), findsWidgets);

    await tester.tap(find.text('浅色'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('settings_we_switch')));
    await tester.pumpAndSettle();

    expect(api.session.themeMode, 'light');
    expect(api.session.biometricEnabled, isFalse);
    expect(api.settingSaves, [
      {'themeMode': 'light'},
      {'biometricEnabled': false},
    ]);
  });

  testWidgets('settings feedback submits through Android app feedback API', (
    WidgetTester tester,
  ) async {
    final api = _FakeSettingsApi();
    tester.view.devicePixelRatio = 1;
    tester.view.physicalSize = const Size(430, 1800);
    addTearDown(tester.view.resetDevicePixelRatio);
    addTearDown(tester.view.resetPhysicalSize);

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: SettingsScreen(api: api),
      ),
    );

    await tester.enterText(find.byType(TextField), '上传图片后列表错位');
    await tester.pump();
    await tester.tap(find.text('提交反馈'));
    await tester.pumpAndSettle();

    expect(api.feedbackMessages, ['上传图片后列表错位']);
    expect(find.text('感谢您的反馈，我们会尽快处理'), findsOneWidget);
    expect(find.text('上传图片后列表错位'), findsNothing);
  });

  testWidgets('settings update check uses Android app config API', (
    WidgetTester tester,
  ) async {
    final api = _FakeSettingsApi();
    tester.view.devicePixelRatio = 1;
    tester.view.physicalSize = const Size(430, 1800);
    addTearDown(tester.view.resetDevicePixelRatio);
    addTearDown(tester.view.resetPhysicalSize);

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: SettingsScreen(api: api),
      ),
    );

    await tester.tap(find.text('检查更新'));
    await tester.pumpAndSettle();

    expect(api.updateChecks, [
      {
        'currentVersionCode': MobileAndroidBuild.versionCode,
        'sku': MobileAndroidBuild.productSku,
      },
    ]);
    expect(find.text('已是最新版本'), findsOneWidget);
  });

  testWidgets('settings update action opens Android package installer', (
    WidgetTester tester,
  ) async {
    final api = _FakeSettingsApi()
      ..updateResult = const MobileUpdateCheckResult(
        available: true,
        force: false,
        versionName: '10.0.1',
        downloadUrl: 'https://xiu-ci.com/download/enterprise/app.apk',
        raw: {'ok': true},
      );
    final installer = _FakeUpdateInstaller(
      message: '系统安装器已打开，请确认安装',
    );
    tester.view.devicePixelRatio = 1;
    tester.view.physicalSize = const Size(430, 1800);
    addTearDown(tester.view.resetDevicePixelRatio);
    addTearDown(tester.view.resetPhysicalSize);

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: SettingsScreen(api: api, updateInstaller: installer),
      ),
    );

    await tester.tap(find.text('检查更新'));
    await tester.pumpAndSettle();
    expect(find.byType(AlertDialog), findsNothing);
    expect(find.byType(WeDialog), findsOneWidget);
    await tester.tap(find.text('去更新'));
    await tester.pumpAndSettle();

    expect(installer.calls, hasLength(1));
    expect(installer.calls.single.downloadUrl,
        'https://xiu-ci.com/download/enterprise/app.apk');
    expect(find.text('系统安装器已打开，请确认安装'), findsOneWidget);
    expect(find.text('已获取安装包下载地址'), findsNothing);
  });

  testWidgets('about page matches Android company and compliance shell', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(theme: AppTheme.light(), home: const AboutScreen()),
    );

    expect(find.text('关于'), findsOneWidget);
    expect(
      find.byKey(const ValueKey('we_top_bar_divider_关于')),
      findsOneWidget,
    );
    expect(find.text('XCAGI'), findsOneWidget);
    expect(find.image(const AssetImage(appLauncherIconAsset)), findsOneWidget);
    expect(find.text(MobileAndroidBuild.displayVersion), findsWidgets);
    expect(find.text('公司'), findsOneWidget);
    expect(find.text('成都修茈科技有限公司'), findsWidgets);
    expect(find.text('官网'), findsOneWidget);
    expect(find.text('https://xiu-ci.com'), findsOneWidget);
    expect(find.text('蜀ICP备2026014056号-3A'), findsOneWidget);
  });

  testWidgets('about page follows Android dark theme tokens', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        darkTheme: AppTheme.dark(),
        themeMode: ThemeMode.dark,
        home: const AboutScreen(),
      ),
    );

    final colors = AppTheme.colors(tester.element(find.byType(AboutScreen)));
    final scaffold = tester.widget<Scaffold>(find.byType(Scaffold));
    final topBar = tester.widget<Container>(
      find.byKey(const ValueKey('we_top_bar_surface_关于')),
    );
    final title = tester.widget<Text>(find.text('XCAGI'));
    final footer = tester
        .widgetList<Text>(
          find.text(AboutScreen.companyName),
        )
        .last;

    expect(scaffold.backgroundColor, colors.surface);
    expect(topBar.color, colors.surface);
    expect(title.style?.color, colors.textPrimary);
    expect(footer.style?.color, colors.textTertiary);
  });

  testWidgets('about website opens Android external browser URL', (
    WidgetTester tester,
  ) async {
    final opened = <Uri>[];

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: AboutScreen(openExternalUrl: (uri) async {
          opened.add(uri);
          return true;
        }),
      ),
    );

    await tester.tap(find.text('官网'));
    await tester.pumpAndSettle();

    expect(opened, [Uri.parse(AboutScreen.brandUrl)]);
    expect(find.byType(DesktopToolWebViewScreen), findsNothing);
  });

  testWidgets('about update check renders Android update prompt', (
    WidgetTester tester,
  ) async {
    final api = _FakeSettingsApi()
      ..updateResult = const MobileUpdateCheckResult(
        available: true,
        force: false,
        versionName: '10.0.1',
        downloadUrl: 'https://xiu-ci.com/download/enterprise/app.apk',
        raw: {'ok': true},
      );

    await tester.pumpWidget(
      MaterialApp(theme: AppTheme.light(), home: AboutScreen(api: api)),
    );

    await tester.tap(find.text('检查更新'));
    await tester.pumpAndSettle();

    expect(api.updateChecks, [
      {
        'currentVersionCode': MobileAndroidBuild.versionCode,
        'sku': MobileAndroidBuild.productSku,
      },
    ]);
    expect(find.text('发现新版本'), findsOneWidget);
    expect(find.byType(AlertDialog), findsNothing);
    expect(find.byType(WeDialog), findsOneWidget);
    expect(
      find.text('最新版本 10.0.1，将下载完整安装包并交给系统安装器安装。'),
      findsOneWidget,
    );
    expect(find.text('去更新'), findsOneWidget);
    expect(find.text('稍后'), findsOneWidget);
  });

  testWidgets('about forced update prompt mirrors Android WeDialog lock', (
    WidgetTester tester,
  ) async {
    final api = _FakeSettingsApi()
      ..updateResult = const MobileUpdateCheckResult(
        available: true,
        force: true,
        versionName: '10.0.2',
        downloadUrl: 'https://xiu-ci.com/download/enterprise/app.apk',
        raw: {'ok': true},
      );

    await tester.pumpWidget(
      MaterialApp(theme: AppTheme.light(), home: AboutScreen(api: api)),
    );

    await tester.tap(find.text('检查更新'));
    await tester.pumpAndSettle();

    expect(find.byType(AlertDialog), findsNothing);
    expect(find.byType(WeDialog), findsOneWidget);
    expect(find.text('需要更新'), findsOneWidget);
    expect(find.text('去更新'), findsOneWidget);
    expect(find.text('稍后'), findsNothing);
  });

  testWidgets('legal consent page matches Android first-run agreement shell', (
    WidgetTester tester,
  ) async {
    var accepted = false;
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: LegalConsentScreen(onAccepted: () => accepted = true),
      ),
    );

    expect(find.text('XCAGI'), findsOneWidget);
    expect(find.image(const AssetImage(appLauncherIconAsset)), findsOneWidget);
    expect(find.text('企业智能工作平台'), findsOneWidget);
    expect(find.text('我已阅读并同意'), findsOneWidget);
    expect(find.text('《用户协议》'), findsOneWidget);
    expect(find.text('《隐私政策》'), findsOneWidget);
    expect(find.text('请先同意协议'), findsOneWidget);
    expect(find.byTooltip('关于'), findsNothing);

    await tester.tap(find.text('我已阅读并同意'));
    await tester.pump();
    await tester.tap(find.text('进入 XCAGI'));
    await tester.pumpAndSettle();
    expect(accepted, isTrue);
  });

  testWidgets('legal consent page follows Android dark theme tokens', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        darkTheme: AppTheme.dark(),
        themeMode: ThemeMode.dark,
        home: const LegalConsentScreen(),
      ),
    );

    final colors =
        AppTheme.colors(tester.element(find.byType(LegalConsentScreen)));
    final scaffold = tester.widget<Scaffold>(find.byType(Scaffold));
    final title = tester.widget<Text>(find.text('XCAGI'));
    final terms = tester.widget<Text>(find.text('《用户协议》'));

    expect(scaffold.backgroundColor, colors.brand);
    expect(title.style?.color, colors.chatUserBubbleText);
    expect(terms.style?.color, colors.chatUserBubbleText);
    expect(terms.style?.decorationColor, colors.chatUserBubbleText);
  });

  testWidgets('legal consent persists Android accepted version', (
    WidgetTester tester,
  ) async {
    final api = _FakeLegalApi();
    var accepted = false;

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: LegalConsentScreen(
          api: api,
          legalVersion: 'legal-2026',
          onAccepted: () => accepted = true,
        ),
      ),
    );

    await tester.tap(find.text('我已阅读并同意'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('进入 XCAGI'));
    await tester.pumpAndSettle();

    expect(api.acceptedVersions, ['legal-2026']);
    expect(accepted, isTrue);
  });

  testWidgets('legal agreement row toggles without opening webview', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: const LegalConsentScreen(),
      ),
    );

    await tester.tap(find.text('《用户协议》'));
    await tester.pumpAndSettle();

    expect(find.text('进入 XCAGI'), findsOneWidget);
    expect(find.byType(DesktopToolWebViewScreen), findsNothing);
  });

  testWidgets('auth page matches Android password phone and scan entry shell', (
    WidgetTester tester,
  ) async {
    tester.view.devicePixelRatio = 1;
    tester.view.physicalSize = const Size(430, 1800);
    addTearDown(tester.view.resetDevicePixelRatio);
    addTearDown(tester.view.resetPhysicalSize);

    await tester.pumpWidget(
      MaterialApp(theme: AppTheme.light(), home: const AuthScreen()),
    );

    expect(find.text('XCAGI 手机控制端'), findsOneWidget);
    expect(find.image(const AssetImage(appLauncherIconAsset)), findsOneWidget);
    expect(find.text('连接服务器后台、企业工作台和电脑执行端'), findsOneWidget);
    expect(find.text('密码登录'), findsOneWidget);
    expect(find.text('手机号登录'), findsOneWidget);
    expect(find.text('企业工作台'), findsOneWidget);
    expect(find.text('服务器后台'), findsOneWidget);
    expect(find.text('扫码绑定/登录'), findsOneWidget);
    expect(find.text('记住密码'), findsOneWidget);
    expect(find.text('免登录'), findsOneWidget);
    expect(find.text('账号注册'), findsNothing);
    expect(find.text('已阅读并同意 '), findsOneWidget);
    expect(find.text('服务协议'), findsOneWidget);
    expect(find.text('隐私政策'), findsOneWidget);

    await tester.tap(find.text('手机号登录'));
    await tester.pump();
    expect(find.text('请输入手机号'), findsOneWidget);
    expect(find.text('验证码'), findsOneWidget);
    expect(find.text('获取验证码'), findsOneWidget);
  });

  testWidgets('auth page follows Android dark theme tokens', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        darkTheme: AppTheme.dark(),
        themeMode: ThemeMode.dark,
        home: const AuthScreen(),
      ),
    );
    await tester.pumpAndSettle();

    final colors = AppTheme.colors(tester.element(find.byType(AuthScreen)));
    final scaffold = tester.widget<Scaffold>(find.byType(Scaffold));
    final title = tester.widget<Text>(find.text('XCAGI 手机控制端'));
    final subtitle = tester.widget<Text>(
      find.text('连接服务器后台、企业工作台和电脑执行端'),
    );
    final selectedTab = tester.widget<Text>(find.text('密码登录'));
    final agreement = tester.widget<Text>(find.text('已阅读并同意 '));

    expect(scaffold.backgroundColor, colors.surface);
    expect(title.style?.color, colors.textPrimary);
    expect(subtitle.style?.color, colors.textSecondary);
    expect(selectedTab.style?.color, colors.brand);
    expect(agreement.style?.color, colors.textSecondary);
  });

  testWidgets('auth page restores and saves Android remembered credentials', (
    WidgetTester tester,
  ) async {
    final api = MobileApiClient(
      sessionStore: MemoryMobileSessionStore(
        const MobileSessionData(
          savedUsername: 'remembered-admin',
          savedPassword: 'secret',
          rememberPassword: true,
          autoLogin: true,
        ),
      ),
    );
    final repository = _FakeAuthRepository(api);

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: AuthScreen(repository: repository),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('remembered-admin'), findsOneWidget);
    expect(find.text('记住密码'), findsOneWidget);
    expect(find.text('免登录'), findsOneWidget);

    await tester.tap(find.widgetWithText(FilledButton, '进入企业工作台'));
    await tester.pumpAndSettle();

    expect(repository.logins, [
      {
        'username': 'remembered-admin',
        'password': 'secret',
        'adminMode': false,
        'rememberPass': true,
        'autoLogin': true,
      },
    ]);
    final saved = await api.loadSession();
    expect(saved.rememberPassword, isTrue);
    expect(saved.autoLogin, isTrue);
    expect(saved.savedUsername, 'remembered-admin');
    expect(saved.savedPassword, 'secret');
  });

  testWidgets('auth agreement links open Android external legal URLs', (
    WidgetTester tester,
  ) async {
    final opened = <Uri>[];
    tester.view.devicePixelRatio = 1;
    tester.view.physicalSize = const Size(430, 1800);
    addTearDown(tester.view.resetDevicePixelRatio);
    addTearDown(tester.view.resetPhysicalSize);

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: AuthScreen(openExternalUrl: (uri) async {
          opened.add(uri);
          return true;
        }),
      ),
    );

    await tester.tap(find.text('服务协议'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('隐私政策'));
    await tester.pumpAndSettle();

    expect(opened, [
      Uri.parse('https://xiu-ci.com/legal/terms'),
      Uri.parse('https://xiu-ci.com/legal/privacy'),
    ]);
    expect(find.byType(DesktopToolWebViewScreen), findsNothing);
  });

  testWidgets('register page matches Android web form handoff shell', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(theme: AppTheme.light(), home: const RegisterScreen()),
    );

    expect(find.text('账号注册'), findsWidgets);
    expect(find.text('使用网页开户注册表单，和桌面端保持一致。'), findsOneWidget);
    expect(find.text('网页登录表单'), findsOneWidget);
    expect(find.textContaining('用户名、邮箱、行业、预算区间、密码和确认密码'), findsOneWidget);
    expect(find.text('去网页填写注册表单'), findsOneWidget);
    expect(find.text('返回登录'), findsOneWidget);
  });

  testWidgets('register page follows Android dark theme tokens', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        darkTheme: AppTheme.dark(),
        themeMode: ThemeMode.dark,
        home: const RegisterScreen(),
      ),
    );

    final colors = AppTheme.colors(tester.element(find.byType(RegisterScreen)));
    final scaffold = tester.widget<Scaffold>(find.byType(Scaffold));
    final topBar = tester.widget<Container>(
      find.byKey(const ValueKey('we_top_bar_surface_账号注册')),
    );
    final title = tester.widgetList<Text>(find.text('账号注册')).last;
    final subtitle = tester.widget<Text>(
      find.text('使用网页开户注册表单，和桌面端保持一致。'),
    );
    final icon = tester.widget<Icon>(find.byIcon(Icons.language));

    expect(scaffold.backgroundColor, colors.page);
    expect(topBar.color, colors.surface);
    expect(title.style?.color, colors.textPrimary);
    expect(subtitle.style?.color, colors.textSecondary);
    expect(icon.color, colors.textPrimary);
  });

  test('register webview intercepts Android completion URL', () {
    var completed = false;
    final handled = handleAndroidRegisterUrlOverride(
      'https://xiu-ci.com/app/mobile-register-complete?ok=1',
      () => completed = true,
    );

    expect(handled, isTrue);
    expect(completed, isTrue);
    expect(
      handleAndroidRegisterUrlOverride(
        'https://xiu-ci.com/login/register',
        () => completed = false,
      ),
      isFalse,
    );
    expect(isAndroidRegisterCompleteUrlForTest('/app/mobile-register-complete'),
        isTrue);
  });

  testWidgets('onboarding page matches Android three step startup flow', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: const MobileOnboardingScreen(
          initialIndustries: [
            OnboardingIndustry(
              id: '通用',
              title: '通用',
              subtitle: '可选行业',
            ),
          ],
        ),
      ),
    );
    await tester.pump();

    expect(find.text('启动配置'), findsOneWidget);
    expect(find.text('认识XC'), findsOneWidget);
    expect(find.text('行业定型'), findsOneWidget);
    expect(find.text('补基础线'), findsOneWidget);
    expect(find.text('移动端将独立连接 XCAGI 宿主'), findsOneWidget);
    expect(find.text('开始行业配置'), findsOneWidget);

    await tester.tap(find.text('开始行业配置'));
    await tester.pump();
    expect(find.text('选择行业'), findsOneWidget);
    expect(find.text('这里使用后端行业目录，和桌面端的行业筛选来源一致。'), findsOneWidget);
    expect(find.text('通用'), findsWidgets);
    expect(find.text('继续'), findsOneWidget);
  });

  testWidgets('onboarding page follows Android dark theme tokens', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        darkTheme: AppTheme.dark(),
        themeMode: ThemeMode.dark,
        home: const MobileOnboardingScreen(
          initialIndustries: [
            OnboardingIndustry(
              id: '通用',
              title: '通用',
              subtitle: '可选行业',
            ),
          ],
        ),
      ),
    );

    final colors =
        AppTheme.colors(tester.element(find.byType(MobileOnboardingScreen)));
    final scaffold = tester.widget<Scaffold>(find.byType(Scaffold));
    final topBar = tester.widget<Container>(
      find.byKey(const ValueKey('we_top_bar_surface_启动配置')),
    );
    final refresh = tester.widget<IconButton>(
      find.widgetWithIcon(IconButton, Icons.refresh),
    );
    final stepTitle = tester.widget<Text>(find.text('认识XC'));

    expect(scaffold.backgroundColor, colors.page);
    expect(topBar.color, colors.surface);
    expect(refresh.color, colors.textPrimary);
    expect(stepTitle.style?.color, colors.brand);
  });

  testWidgets('market page matches Android MODstore sections', (
    WidgetTester tester,
  ) async {
    tester.view.devicePixelRatio = 1;
    tester.view.physicalSize = const Size(430, 1800);
    addTearDown(tester.view.resetDevicePixelRatio);
    addTearDown(tester.view.resetPhysicalSize);

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: const MarketListScreen(
          initialIndustries: [
            OnboardingIndustry(
              id: '通用',
              title: '通用',
              subtitle: '装齐行业基础能力',
            ),
          ],
          initialPlans: [
            PaymentPlan(
              id: 'pro',
              title: 'Pro 套餐',
              subtitle: '市场统一收银台',
            ),
          ],
          initialCapabilities: [
            MarketCapability(
              id: 'chart-dashboard-employee',
              title: '综合看板可视化员',
              subtitle: '从企业端同步的能力包',
            ),
          ],
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('MODstore'), findsOneWidget);
    expect(
      find.byKey(const ValueKey('we_top_bar_divider_MODstore')),
      findsOneWidget,
    );
    expect(find.text('行业初始化'), findsOneWidget);
    expect(find.text('模型服务'), findsOneWidget);
    expect(find.text('手机充值渠道'), findsOneWidget);
    expect(find.text('钱包充值'), findsOneWidget);
    expect(find.text('可用能力'), findsOneWidget);
    expect(find.text('综合看板可视化员'), findsOneWidget);
    expect(find.text('装齐'), findsOneWidget);
    expect(find.text('购买'), findsOneWidget);
    expect(find.text('使用'), findsOneWidget);
  });

  testWidgets('market page follows Android dark theme tokens', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        darkTheme: AppTheme.dark(),
        themeMode: ThemeMode.dark,
        home: const MarketListScreen(
          initialIndustries: [
            OnboardingIndustry(
              id: '通用',
              title: '通用',
              subtitle: '装齐行业基础能力',
            ),
          ],
          initialPlans: [
            PaymentPlan(
              id: 'pro',
              title: 'Pro 套餐',
              subtitle: '市场统一收银台',
            ),
          ],
          initialCapabilities: [
            MarketCapability(
              id: 'chart-dashboard-employee',
              title: '综合看板可视化员',
              subtitle: '从企业端同步的能力包',
            ),
          ],
        ),
      ),
    );
    await tester.pumpAndSettle();

    final colors =
        AppTheme.colors(tester.element(find.byType(MarketListScreen)));
    final scaffold = tester.widget<Scaffold>(find.byType(Scaffold));
    final topBar = tester.widget<Container>(
      find.byKey(const ValueKey('we_top_bar_surface_MODstore')),
    );
    final refresh = tester.widget<IconButton>(
      find.widgetWithIcon(IconButton, Icons.refresh),
    );
    final industryIcon = tester.widget<Icon>(
      find.byKey(const ValueKey('we_cell_icon_通用')),
    );

    expect(scaffold.backgroundColor, colors.page);
    expect(topBar.color, colors.surface);
    expect(refresh.color, colors.textPrimary);
    expect(industryIcon.color, colors.brand);
  });

  testWidgets('approval list and detail match Android approval flow shell', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: const ApprovalListScreen(
          initialItems: [
            ApprovalRequest(
              id: 7,
              title: '采购审批',
              subtitle: '张三',
              status: '待处理',
              applicantName: '张三',
            ),
          ],
        ),
      ),
    );
    await tester.pump();

    expect(find.text('审批'), findsOneWidget);
    expect(find.text('待处理'), findsWidgets);
    expect(find.text('采购审批'), findsOneWidget);
    expect(find.text('张三'), findsOneWidget);

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: const ApprovalDetailScreen(
          id: 7,
          initialDetail: ApprovalDetail(
            id: 7,
            requestNo: 'AP-7',
            title: '采购审批',
            status: 'pending',
            applicantName: '张三',
            flowName: '采购流程',
            currentNodeName: '主管审批',
            submittedAt: '2026-06-30',
            description: '采购一批物料',
          ),
        ),
      ),
    );
    await tester.pump();

    expect(find.text('审批信息'), findsOneWidget);
    expect(find.text('单号'), findsOneWidget);
    expect(find.text('AP-7'), findsOneWidget);
    expect(find.text('审批意见'), findsOneWidget);
    expect(find.text('复杂编辑请在电脑端处理'), findsOneWidget);
    expect(find.text('通过'), findsOneWidget);
    expect(find.text('驳回'), findsOneWidget);
    expect(find.byType(WeBlockButton), findsOneWidget);
    expect(find.byType(WeBlockOutlinedButton), findsOneWidget);
    expect(
      tester.getSize(find.byType(FilledButton).last).height,
      44,
    );
    expect(
      tester.getSize(find.byType(OutlinedButton).last).height,
      48,
    );

    await tester.tap(find.text('驳回'));
    await tester.pumpAndSettle();

    expect(find.byType(AlertDialog), findsNothing);
    expect(find.byType(WeDialog), findsOneWidget);
    expect(find.text('确认驳回'), findsOneWidget);
    expect(find.text('确定驳回该审批？'), findsOneWidget);
    final rejectConfirm = tester.widget<Text>(
      find.descendant(
        of: find.byKey(const ValueKey('we_dialog_confirm')),
        matching: find.text('确定'),
      ),
    );
    expect(rejectConfirm.style?.color, AppTheme.danger);

    await tester.tap(find.byKey(const ValueKey('we_dialog_dismiss')));
    await tester.pumpAndSettle();

    await tester.tap(find.text('通过'));
    await tester.pumpAndSettle();

    expect(find.byType(AlertDialog), findsNothing);
    expect(find.byType(WeDialog), findsOneWidget);
    expect(find.text('确认通过'), findsOneWidget);
    expect(find.text('确定通过该审批？'), findsOneWidget);
  });

  testWidgets('approval page follows Android dark theme tokens', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        darkTheme: AppTheme.dark(),
        themeMode: ThemeMode.dark,
        home: const ApprovalListScreen(
          initialItems: [
            ApprovalRequest(
              id: 7,
              title: '采购审批',
              subtitle: '张三',
              status: '待处理',
              applicantName: '张三',
            ),
          ],
        ),
      ),
    );
    await tester.pump();

    final colors =
        AppTheme.colors(tester.element(find.byType(ApprovalListScreen)));
    final scaffold = tester.widget<Scaffold>(find.byType(Scaffold));
    final topBar = tester.widget<Container>(
      find.byKey(const ValueKey('we_top_bar_surface_审批')),
    );
    final refresh = tester.widget<IconButton>(
      find.widgetWithIcon(IconButton, Icons.refresh),
    );
    final title = tester.widget<Text>(find.text('采购审批'));

    expect(scaffold.backgroundColor, colors.page);
    expect(topBar.color, colors.surface);
    expect(refresh.color, colors.textPrimary);
    expect(title.style?.color, colors.textPrimary);
  });

  testWidgets('IM page matches Android direct conversation shell', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(theme: AppTheme.light(), home: const ImMessengerScreen()),
    );

    expect(find.text('IM 消息'), findsOneWidget);
    expect(
      find.byKey(const ValueKey('we_top_bar_divider_IM 消息')),
      findsOneWidget,
    );
    expect(find.text('新会话'), findsOneWidget);
    expect(find.text('对方用户'), findsOneWidget);
    expect(find.text('用户 ID'), findsOneWidget);
    expect(find.text('打开会话'), findsOneWidget);

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: const ImMessengerScreen(
          key: ValueKey('im-conversation'),
          initialConversationId: 12,
          initialMessages: [
            ImMessage(
              id: 1,
              senderUserId: 0,
              body: '你好',
              createdAt: '刚刚',
            ),
          ],
        ),
      ),
    );
    await tester.pump();

    expect(find.text('会话 #12'), findsOneWidget);
    expect(find.text('WebSocket 已连接，消息实时同步'), findsOneWidget);
    expect(find.text('用户 0'), findsOneWidget);
    expect(find.text('你好'), findsOneWidget);
    expect(find.text('输入消息'), findsOneWidget);
  });

  testWidgets('IM page follows Android dark theme tokens', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        darkTheme: AppTheme.dark(),
        themeMode: ThemeMode.dark,
        home: const ImMessengerScreen(
          initialConversationId: 12,
          initialMessages: [
            ImMessage(
              id: 1,
              senderUserId: 0,
              body: '我发的',
              createdAt: '刚刚',
            ),
            ImMessage(
              id: 2,
              senderUserId: 99,
              body: '对方的',
              createdAt: '刚刚',
            ),
          ],
        ),
      ),
    );

    final colors =
        AppTheme.colors(tester.element(find.byType(ImMessengerScreen)));
    final scaffold = tester.widget<Scaffold>(find.byType(Scaffold));
    final inputBar = tester.widget<Container>(
      find.byKey(const ValueKey('im_input_bar_surface')),
    );
    final mineBubble = tester.widget<Container>(
      find.byKey(const ValueKey('im_bubble_1')),
    );
    final peerBubble = tester.widget<Container>(
      find.byKey(const ValueKey('im_bubble_2')),
    );

    expect(scaffold.backgroundColor, colors.surface);
    expect(inputBar.color, colors.surface);
    expect(
      (mineBubble.decoration as BoxDecoration).color,
      colors.brand,
    );
    expect(
      (peerBubble.decoration as BoxDecoration).color,
      colors.surfaceHigh,
    );
  });

  testWidgets('IM message menu mirrors Android reply and delete actions', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: const ImMessengerScreen(
          initialConversationId: 12,
          initialMessages: [
            ImMessage(
              id: 1,
              senderUserId: 0,
              body: '你好',
              createdAt: '刚刚',
            ),
          ],
        ),
      ),
    );
    await tester.pump();

    await tester.longPress(find.text('你好'));
    await tester.pumpAndSettle();

    expect(find.text('复制'), findsOneWidget);
    expect(find.text('引用'), findsOneWidget);
    expect(find.text('删除'), findsOneWidget);

    await tester.tap(find.text('引用'));
    await tester.pumpAndSettle();

    final field = tester.widget<TextField>(find.byType(TextField));
    expect(field.controller?.text, '引用「你好」\n');

    await tester.longPress(find.text('你好'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('删除'));
    await tester.pumpAndSettle();

    expect(find.text('你好'), findsNothing);
  });

  testWidgets('bridge page matches Android service bridge shell', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: const BridgeScreen(
          initialItems: [
            BusinessListItem(
              id: '7',
              title: '客户验收回访',
              subtitle: 'pending',
            ),
          ],
        ),
      ),
    );
    await tester.pump();

    expect(find.text('服务桥接'), findsOneWidget);
    expect(
      find.byKey(const ValueKey('we_top_bar_divider_服务桥接')),
      findsOneWidget,
    );
    expect(find.text('待处理工单'), findsOneWidget);
    expect(find.text('客户验收回访'), findsOneWidget);
    expect(find.text('回复'), findsOneWidget);
    expect(find.text('输入处理意见或补充说明'), findsOneWidget);
    expect(find.text('发送回复'), findsOneWidget);

    await tester.tap(find.text('客户验收回访'));
    await tester.pump();

    expect(find.text('回复 #7'), findsOneWidget);
  });

  testWidgets('customer service bridge filters and replies customer requests', (
    WidgetTester tester,
  ) async {
    final repository = _FakeBridgeRepository(
      const [
        BusinessListItem(
          id: '9',
          title: '我想买企业版',
          subtitle: 'pending',
          payload: {
            'source_instance_name': '手机端 Alice',
            'description': '我想买企业版',
            'status': 'pending',
          },
        ),
      ],
    );

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: BridgeScreen.customerService(repository: repository),
      ),
    );
    await tester.pumpAndSettle();

    expect(repository.bridgeRequestTypes, [
      MobileRepository.customerServiceRequestType,
    ]);
    expect(find.text('客户客服'), findsOneWidget);
    expect(find.text('客户消息'), findsOneWidget);
    expect(find.text('手机端 Alice'), findsWidgets);
    expect(find.text('我想买企业版 · pending'), findsOneWidget);
    expect(find.text('回复客户 #9'), findsOneWidget);
    expect(find.text('输入给客户的回复'), findsOneWidget);

    await tester.tap(find.text('手机端 Alice').first);
    await tester.pump();
    expect(find.text('回复客户 #9'), findsOneWidget);
    await tester.enterText(find.byType(TextField), '我来跟进企业版开通');
    await tester.pump();
    await tester.ensureVisible(find.text('发送回复'));
    await tester.tap(find.text('发送回复'));
    await tester.pumpAndSettle();

    expect(repository.replies, [
      {
        'id': 9,
        'response': '我来跟进企业版开通',
        'respondedBy': 'mobile-admin-customer-service',
      },
    ]);
    expect(repository.bridgeRequestTypes.last,
        MobileRepository.customerServiceRequestType);
  });

  testWidgets('bridge page follows Android dark theme tokens', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        darkTheme: AppTheme.dark(),
        themeMode: ThemeMode.dark,
        home: const BridgeScreen(
          initialItems: [
            BusinessListItem(
              id: '7',
              title: '客户验收回访',
              subtitle: 'pending',
            ),
          ],
        ),
      ),
    );
    await tester.pump();

    final colors = AppTheme.colors(tester.element(find.byType(BridgeScreen)));
    final scaffold = tester.widget<Scaffold>(find.byType(Scaffold));
    final topBar = tester.widget<Container>(
      find.byKey(const ValueKey('we_top_bar_surface_服务桥接')),
    );
    final icon = tester.widget<Icon>(
      find.byKey(const ValueKey('we_cell_icon_客户验收回访')),
    );
    final input = tester.widget<TextField>(find.byType(TextField));

    expect(scaffold.backgroundColor, colors.surface);
    expect(topBar.color, colors.surface);
    expect(icon.color, colors.textSecondary);
    expect(input.style?.color, colors.textPrimary);
    expect(input.decoration?.hintStyle?.color,
        colors.textSecondary.withValues(alpha: 0.6));
  });

  testWidgets('ERP page matches Android customer shipment inventory tabs', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: const ErpScreen(
          initialItemsByKind: {
            BusinessListKind.customers: [
              BusinessListItem(
                id: 'c1',
                title: '上海客户',
                subtitle: 'active',
              ),
            ],
            BusinessListKind.shipments: [],
          },
        ),
      ),
    );
    await tester.pump();

    expect(find.text('业务'), findsOneWidget);
    expect(find.text('客户'), findsWidgets);
    expect(find.text('发货'), findsOneWidget);
    expect(find.text('库存'), findsOneWidget);
    expect(find.text('客户记录'), findsOneWidget);
    expect(find.text('上海客户'), findsOneWidget);

    await tester.tap(find.text('发货'));
    await tester.pumpAndSettle();

    expect(find.text('发货记录'), findsOneWidget);
    expect(find.text('暂无发货数据'), findsOneWidget);
    expect(find.text('下拉刷新或连接电脑后重试。'), findsOneWidget);
    expect(find.text('刷新'), findsOneWidget);
  });

  testWidgets('business list page matches Android generic list shell', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: const BusinessListScreen(
          kind: BusinessListKind.shipments,
          initialItems: [
            BusinessListItem(
              id: 's1',
              title: '发货单 SO-1',
              subtitle: 'shipped',
            ),
          ],
        ),
      ),
    );
    await tester.pump();

    expect(find.text('发货'), findsWidgets);
    expect(find.text('发货单 SO-1'), findsOneWidget);
    expect(find.text('shipped'), findsOneWidget);
  });

  testWidgets('business list page mirrors Android loading and error states', (
    WidgetTester tester,
  ) async {
    final repository = _SlowBusinessRepository();

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: BusinessListScreen(
          kind: BusinessListKind.shipments,
          repository: repository,
        ),
      ),
    );
    await tester.pump();

    expect(
        find.byKey(const ValueKey('business_list_skeleton_0')), findsOneWidget);

    repository.shipments.completeError(
      const MobileRepositoryException('发货加载失败'),
    );
    await tester.pumpAndSettle();

    expect(find.text('加载失败'), findsOneWidget);
    expect(find.text('发货加载失败'), findsOneWidget);
    expect(find.text('重试'), findsOneWidget);
  });

  testWidgets('business list page follows Android dark theme tokens', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        darkTheme: AppTheme.dark(),
        themeMode: ThemeMode.dark,
        home: const BusinessListScreen(
          kind: BusinessListKind.shipments,
          initialItems: [
            BusinessListItem(
              id: 's1',
              title: '发货单 SO-1',
              subtitle: 'shipped',
            ),
          ],
        ),
      ),
    );
    await tester.pump();

    final colors =
        AppTheme.colors(tester.element(find.byType(BusinessListScreen)));
    final scaffold = tester.widget<Scaffold>(find.byType(Scaffold));
    final topBar = tester.widget<Container>(
      find.byKey(const ValueKey('we_top_bar_surface_发货')),
    );
    final title = tester.widget<Text>(find.text('发货单 SO-1'));

    expect(scaffold.backgroundColor, colors.page);
    expect(topBar.color, colors.surface);
    expect(title.style?.color, colors.textPrimary);
  });

  testWidgets('longtail finance page matches Android finance summary shell', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: const LongTailScreen(
          initialDetail: '{success=true, data={income=100,cost=40,profit=60}}',
        ),
      ),
    );
    await tester.pump();

    expect(find.text('财务摘要'), findsOneWidget);
    expect(
      find.byKey(const ValueKey('we_top_bar_divider_财务摘要')),
      findsOneWidget,
    );
    expect(find.text('概览'), findsOneWidget);
    expect(find.text('财务看板已同步'), findsOneWidget);
    expect(find.text('操作'), findsOneWidget);
    expect(find.text('凭证与收支'), findsOneWidget);
    expect(find.text('标签打印'), findsOneWidget);

    await tester.tap(find.text('凭证与收支'));
    await tester.pumpAndSettle();
    expect(find.text('请在电脑端打开完整财务看板'), findsOneWidget);
    await tester.pump(const Duration(seconds: 4));
    await tester.pumpAndSettle();
    await tester.tap(find.text('标签打印'));
    await tester.pumpAndSettle();
    expect(find.text('请在电脑端完成标签打印'), findsOneWidget);
  });

  testWidgets('longtail finance page follows Android dark theme tokens', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        darkTheme: AppTheme.dark(),
        themeMode: ThemeMode.dark,
        home: const LongTailScreen(
          initialDetail: '{success=true, data={income=100,cost=40,profit=60}}',
        ),
      ),
    );
    await tester.pump();

    final colors = AppTheme.colors(tester.element(find.byType(LongTailScreen)));
    final scaffold = tester.widget<Scaffold>(find.byType(Scaffold));
    final topBar = tester.widget<Container>(
      find.byKey(const ValueKey('we_top_bar_surface_财务摘要')),
    );
    final overviewIcon = tester.widget<Icon>(
      find.byKey(const ValueKey('we_cell_icon_财务看板已同步')),
    );
    final voucherIcon = tester.widget<Icon>(
      find.byKey(const ValueKey('we_cell_icon_凭证与收支')),
    );

    expect(scaffold.backgroundColor, colors.page);
    expect(topBar.color, colors.surface);
    expect(overviewIcon.color, colors.brand);
    expect(voucherIcon.color, colors.success);
  });

  testWidgets('enterprise module placeholders match Android branded entries', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: EnterpriseModuleScreen.brain(),
      ),
    );

    expect(find.text('智脑集成'), findsWidgets);
    expect(
      find.byKey(const ValueKey('we_top_bar_divider_智脑集成')),
      findsOneWidget,
    );
    expect(find.text('员工编排由企业端模块承载'), findsOneWidget);
    expect(find.text('打开能力库'), findsOneWidget);

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: EnterpriseModuleScreen.modStore(),
      ),
    );

    expect(find.text('能力库'), findsWidgets);
    expect(find.text('安装与授权由企业端和管理端统一管理'), findsOneWidget);
    expect(find.text('查看企业模块'), findsOneWidget);
  });

  testWidgets('enterprise module placeholders follow Android dark theme tokens',
      (WidgetTester tester) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        darkTheme: AppTheme.dark(),
        themeMode: ThemeMode.dark,
        home: EnterpriseModuleScreen.brain(),
      ),
    );

    final colors =
        AppTheme.colors(tester.element(find.byType(EnterpriseModuleScreen)));
    final scaffold = tester.widget<Scaffold>(find.byType(Scaffold));
    final topBar = tester.widget<Container>(
      find.byKey(const ValueKey('we_top_bar_surface_智脑集成')),
    );
    final title = tester.widget<Text>(find.text('智脑集成').last);

    expect(scaffold.backgroundColor, colors.page);
    expect(topBar.color, colors.surface);
    expect(title.style?.color, colors.textPrimary);
  });

  test('webview URL and token injection match Android policy', () {
    const config = MobileApiConfig(
      baseUrl: 'https://xiu-ci.com/fhd-api',
      marketAccessToken: 'market-access',
      marketRefreshToken: 'market-refresh',
      accessToken: 'fhd-access',
    );

    final desktop = resolveAndroidDesktopWebUriForTest(
      '/customers?sku=enterprise',
      config: config,
    );
    expect(
      desktop.toString(),
      'https://xiu-ci.com/fhd-api/customers?sku=enterprise&shell=1',
    );

    final mod = resolveAndroidModWebUriForTest(
      'attendance-industry',
      config: config,
    );
    expect(
      mod.toString(),
      'https://xiu-ci.com/fhd-api/mod/attendance-industry/?shell=1',
    );

    final script = buildAndroidTokenInjectScriptForTest(
      accessToken: 'market-access',
      refreshToken: 'market-refresh',
      fhdAccessToken: 'fhd-access',
    );
    expect(script, contains("localStorage.setItem('modstore_token'"));
    expect(script, contains("localStorage.setItem('modstore_refresh_token'"));
    expect(script, contains("document.cookie = 'session_id=fhd-access"));
    expect(script, contains("window.__XCAGI_CLIENT__ = 'android'"));
    expect(script, contains('xcagi-client-android'));
  });

  testWidgets('customer service chat matches Android CS shell', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: CsChatScreen(repository: _FakeRealtimeRepository()),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('专属客服'), findsOneWidget);
    expect(find.text('客服在线'), findsOneWidget);
    expect(find.text('欢迎使用专属客服'), findsOneWidget);
    expect(find.text('输入消息...'), findsOneWidget);
    expect(find.text('发送'), findsNothing);
    expect(find.byTooltip('发送'), findsOneWidget);
    expect(find.byTooltip('语音'), findsOneWidget);

    await tester.enterText(find.byType(TextField), '我需要帮助');
    await tester.tap(find.byTooltip('发送'));
    await tester.pumpAndSettle();

    expect(find.text('我需要帮助'), findsOneWidget);
    expect(find.text('我来处理'), findsOneWidget);
  });

  testWidgets('customer service chat follows Android dark theme tokens', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        darkTheme: AppTheme.dark(),
        themeMode: ThemeMode.dark,
        home: CsChatScreen(repository: _FakeRealtimeRepository()),
      ),
    );
    await tester.pumpAndSettle();

    final colors = AppTheme.colors(tester.element(find.byType(CsChatScreen)));
    final scaffold = tester.widget<Scaffold>(find.byType(Scaffold));
    final inputBar = tester.widget<Container>(
      find.byKey(const ValueKey('cs_input_bar_surface')),
    );
    final assistantBubble = tester.widget<Material>(
      find.byKey(const ValueKey('cs_bubble_cs-1')),
    );
    final inputDecoration = inputBar.decoration as BoxDecoration;

    expect(scaffold.backgroundColor, colors.page);
    expect(inputDecoration.color, colors.surface);
    expect(inputDecoration.border?.top.color, colors.weChatDivider);
    expect(assistantBubble.color, colors.surface);
  });

  testWidgets('customer service voice opens Android voice sheet', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: CsChatScreen(repository: _FakeRealtimeRepository()),
      ),
    );
    await tester.pumpAndSettle();

    await tester.tap(find.byTooltip('语音'));
    await tester.pump(const Duration(milliseconds: 300));

    expect(find.text('语音输入'), findsWidgets);
    expect(find.text('取消'), findsOneWidget);
    expect(find.text('需要麦克风权限才能使用语音输入'), findsNothing);
  });

  testWidgets('voice input sheet follows Android dark theme tokens', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        darkTheme: AppTheme.dark(),
        themeMode: ThemeMode.dark,
        home: CsChatScreen(repository: _FakeRealtimeRepository()),
      ),
    );
    await tester.pumpAndSettle();

    await tester.tap(find.byTooltip('语音'));
    await tester.pump(const Duration(milliseconds: 300));

    final colors = AppTheme.colors(tester.element(find.byType(CsChatScreen)));
    final title = tester.widget<Text>(find.text('语音输入').first);

    expect(title.style?.color, colors.textPrimary);
  });

  testWidgets('customer service message menu mirrors Android actions', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: CsChatScreen(repository: _FakeRealtimeRepository()),
      ),
    );
    await tester.pumpAndSettle();

    await tester.longPress(find.text('欢迎使用专属客服'));
    await tester.pumpAndSettle();

    expect(find.text('复制'), findsOneWidget);
    expect(find.text('引用'), findsOneWidget);
    expect(find.text('删除'), findsOneWidget);

    await tester.tap(find.text('引用'));
    await tester.pumpAndSettle();

    final csInput = tester.widget<TextField>(find.byType(TextField));
    expect(csInput.controller?.text, '引用「欢迎使用专属客服」\n');

    await tester.longPress(find.text('欢迎使用专属客服'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('删除'));
    await tester.pumpAndSettle();

    expect(find.text('欢迎使用专属客服'), findsNothing);
  });

  testWidgets('AI group list uses Android group operations shell', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: AiGroupListScreen(repository: _FakeRealtimeRepository()),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('群聊'), findsOneWidget);
    expect(find.text('超级开发部'), findsOneWidget);
    expect(find.text('(2)'), findsOneWidget);

    await tester.longPress(find.text('超级开发部'));
    await tester.pumpAndSettle();

    expect(find.text('标为未读'), findsOneWidget);
    expect(find.text('置顶聊天'), findsOneWidget);
    expect(find.text('不再关注'), findsOneWidget);
    expect(find.text('删除该聊天'), findsOneWidget);
    expect(
      tester.getSize(find.widgetWithText(TextButton, '标为未读')).height,
      52,
    );
  });

  testWidgets('AI group chat matches Android composer tools', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: AiGroupChatScreen(
          repository: _FakeRealtimeRepository(),
          initialGroup: _fakeGroup,
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('超级开发部'), findsOneWidget);
    expect(find.text('2 个 AI 成员'), findsOneWidget);
    expect(find.text('先评估任务，再派给最合适的人。'), findsOneWidget);
    expect(find.text('工作分支 · 自动新建'), findsOneWidget);
    expect(find.text('发群消息（@成员 可单独点名）'), findsOneWidget);
    expect(find.byTooltip('语音'), findsOneWidget);
    expect(find.byTooltip('更多工具'), findsOneWidget);
    expect(find.text('发送'), findsNothing);
    final typography = AppTheme.light().textTheme;
    final inputBar = tester.widget<Container>(
      find.byKey(const ValueKey('group_input_bar_surface')),
    );
    final inputBarDecoration = inputBar.decoration as BoxDecoration;
    final inputBarBorder = inputBarDecoration.border as Border;
    expect(
        inputBarBorder.top.color, AppTheme.light().colorScheme.outlineVariant);
    expect(inputBarBorder.top.width, 0.5);
    final groupTextField = tester.widget<TextField>(find.byType(TextField));
    expect(groupTextField.style?.fontSize, typography.bodyMedium?.fontSize);
    expect(groupTextField.style?.height, typography.bodyMedium?.height);
    expect(groupTextField.decoration?.hintStyle?.fontSize,
        typography.bodyMedium?.fontSize);
    expect(groupTextField.decoration?.hintStyle?.height,
        typography.bodyMedium?.height);
    final branchChip = tester.widget<Text>(find.text('工作分支 · 自动新建'));
    expect(branchChip.style?.fontSize, typography.labelMedium?.fontSize);
    expect(branchChip.style?.height, typography.labelMedium?.height);
    expect(
      tester.getTopLeft(find.byKey(const ValueKey('group_branch_chip'))).dx -
          tester
              .getTopLeft(find.byKey(const ValueKey('group_input_bar_surface')))
              .dx,
      12,
    );

    await tester.tap(find.byTooltip('更多工具'));
    await tester.pumpAndSettle();

    final expandedMoreIcon = tester.widget<Icon>(
      find.descendant(
        of: find.byTooltip('更多工具'),
        matching: find.byIcon(Icons.add),
      ),
    );
    expect(expandedMoreIcon.color, AppTheme.brand);
    expect(
      find.descendant(
        of: find.byTooltip('更多工具'),
        matching: find.byIcon(Icons.close),
      ),
      findsNothing,
    );
    expect(find.text('任务派工'), findsOneWidget);
    expect(find.text('验收回访'), findsOneWidget);
    expect(find.text('问题修复'), findsOneWidget);
    expect(
      tester.widget<Text>(find.text('任务派工')).style?.color,
      AppTheme.textSecondary,
    );
    expect(
      tester.getSize(find.byKey(const ValueKey('group_tool_card_任务派工'))).height,
      92,
    );
    expect(
      tester.getSize(find.byKey(const ValueKey('group_tool_icon_box_任务派工'))),
      const Size(62, 62),
    );
    final dispatchToolLabel = tester.widget<Text>(find.text('任务派工'));
    expect(dispatchToolLabel.style?.fontSize, typography.labelMedium?.fontSize);
    expect(dispatchToolLabel.style?.height, typography.labelMedium?.height);

    await tester.tap(find.text('任务派工'));
    await tester.pumpAndSettle();

    expect(find.text('工作模式 · 任务派工'), findsOneWidget);
    expect(find.text('输入要派发的任务'), findsOneWidget);
    expect(find.text('发送'), findsNothing);
  });

  testWidgets('AI group chat follows Android dark theme tokens', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        darkTheme: AppTheme.dark(),
        themeMode: ThemeMode.dark,
        home: AiGroupChatScreen(
          repository: _FakeRealtimeRepository(),
          initialGroup: _fakeGroup,
        ),
      ),
    );
    await tester.pumpAndSettle();

    final colors =
        AppTheme.colors(tester.element(find.byType(AiGroupChatScreen)));
    final scaffold = tester.widget<Scaffold>(find.byType(Scaffold));
    final inputBar = tester.widget<Container>(
      find.byKey(const ValueKey('group_input_bar_surface')),
    );
    final inputDecoration = inputBar.decoration as BoxDecoration;
    final inputBorder = inputDecoration.border as Border;

    expect(scaffold.backgroundColor, colors.page);
    expect(inputDecoration.color, colors.surface);
    expect(
        inputBorder.top.color,
        Theme.of(tester.element(find.byType(AiGroupChatScreen)))
            .colorScheme
            .outlineVariant);
    final aiBubble = tester.widget<Container>(
      find.byKey(const ValueKey('group_bubble_m1')),
    );
    final discussionBadge = tester.widget<Text>(find.text('讨论'));

    expect(
      (aiBubble.decoration as BoxDecoration).color,
      colors.brand.withValues(alpha: 0.10),
    );
    expect(discussionBadge.style?.color, colors.brand);

    await tester.enterText(find.byType(TextField), '继续');
    await tester.pump();
    await tester.tap(find.text('发送'));
    await tester.pumpAndSettle();

    final userBubble = tester.widget<Container>(
      find.byKey(const ValueKey('group_bubble_user-1')),
    );

    expect(
        (userBubble.decoration as BoxDecoration).color, colors.chatUserBubble);
  });

  testWidgets('AI group branch picker mirrors Android refresh sheet', (
    WidgetTester tester,
  ) async {
    final repository = _FakeEmptyThenBranchRepository();
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: AiGroupChatScreen(
          repository: repository,
          initialGroup: _fakeGroup,
        ),
      ),
    );
    await tester.pumpAndSettle();

    await tester.tap(find.text('工作分支 · 自动新建'));
    await tester.pumpAndSettle();

    expect(find.text('工作分支'), findsOneWidget);
    expect(find.byTooltip('刷新分支'), findsOneWidget);
    expect(find.text('自动新建任务分支'), findsOneWidget);
    expect(find.text('普通派工默认隔离，跑完后再合并'), findsOneWidget);
    expect(find.text('暂无可选分支，点右上角刷新'), findsOneWidget);

    await tester.tap(find.byTooltip('刷新分支'));
    await tester.pumpAndSettle();

    expect(find.text('feature/refreshed'), findsOneWidget);
    expect(find.text('远端分支'), findsOneWidget);
  });

  testWidgets('AI group members sheet uses Android local member catalog', (
    WidgetTester tester,
  ) async {
    final repository = _FakeRealtimeRepository();
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: AiGroupChatScreen(
          repository: repository,
          initialGroup: _fakeGroup,
        ),
      ),
    );
    await tester.pumpAndSettle();

    await tester.tap(find.byTooltip('群成员'));
    await tester.pumpAndSettle();

    expect(find.text('群成员（2）'), findsOneWidget);
    expect(find.text('添加 AI 成员'), findsOneWidget);
    expect(find.text('超级员工-Codex'), findsOneWidget);
    expect(find.text('超级员工-Cursor'), findsOneWidget);
    expect(find.text('超级员工-Claude'), findsOneWidget);
    await tester.scrollUntilVisible(
      find.text('超级员工-Trae'),
      120,
      scrollable: find.byType(Scrollable).last,
    );
    expect(find.text('超级员工-Trae'), findsOneWidget);
    expect(find.text('已把所有 AI 员工都拉进群了'), findsNothing);
    expect(repository.employeeLoads, 1);
    expect(repository.candidateLoads, 0);
  });

  testWidgets('AI group message menu mirrors Android actions', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: AiGroupChatScreen(
          repository: _FakeRealtimeRepository(),
          initialGroup: _fakeGroup,
        ),
      ),
    );
    await tester.pumpAndSettle();

    await tester.longPress(find.text('先评估任务，再派给最合适的人。'));
    await tester.pumpAndSettle();

    expect(find.text('复制'), findsOneWidget);
    expect(find.text('引用'), findsOneWidget);
    expect(find.text('删除'), findsOneWidget);

    await tester.tap(find.text('引用'));
    await tester.pumpAndSettle();

    final groupInput = tester.widget<TextField>(find.byType(TextField).first);
    expect(groupInput.controller?.text, '引用「先评估任务，再派给最合适的人。」\n');

    await tester.longPress(find.text('先评估任务，再派给最合适的人。'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('删除'));
    await tester.pumpAndSettle();

    expect(find.text('先评估任务，再派给最合适的人。'), findsNothing);
  });

  testWidgets('AI group chat voice opens Android voice sheet', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: AiGroupChatScreen(
          repository: _FakeRealtimeRepository(),
          initialGroup: _fakeGroup,
        ),
      ),
    );
    await tester.pumpAndSettle();

    await tester.tap(find.byTooltip('语音'));
    await tester.pump(const Duration(milliseconds: 300));

    expect(find.text('语音输入'), findsWidgets);
    expect(find.text('取消'), findsOneWidget);
    expect(find.text('需要麦克风权限才能使用语音输入'), findsNothing);
  });

  testWidgets('AI group work modes post Android tool_action payloads', (
    WidgetTester tester,
  ) async {
    final repository = _FakeRealtimeRepository();
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: AiGroupChatScreen(
          repository: repository,
          initialGroup: _fakeGroup,
        ),
      ),
    );
    await tester.pumpAndSettle();

    await tester.tap(find.byTooltip('更多工具'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('任务派工'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField).first, '修复 Flutter 群聊派工');
    await tester.pumpAndSettle();
    expect(find.text('发送'), findsOneWidget);
    await tester.tap(find.text('发送'));
    await tester.pumpAndSettle();

    expect(repository.groupPostCalls, hasLength(1));
    expect(repository.groupPostCalls.single['message'], '修复 Flutter 群聊派工');
    expect(repository.groupPostCalls.single['forceDispatch'], true);
    expect(repository.groupPostCalls.single['branchContext'], '');
    expect(
      repository.groupPostCalls.single['context'],
      {'tool_action': 'dispatch_task'},
    );
  });

  testWidgets('AI group followup sends Android default acceptance prompt', (
    WidgetTester tester,
  ) async {
    final repository = _FakeRealtimeRepository();
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: AiGroupChatScreen(
          repository: repository,
          initialGroup: _fakeGroup,
        ),
      ),
    );
    await tester.pumpAndSettle();

    await tester.tap(find.byTooltip('更多工具'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('验收回访'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('发送'));
    await tester.pumpAndSettle();

    expect(repository.groupPostCalls, hasLength(1));
    expect(
      repository.groupPostCalls.single['message'],
      '小C，回访一下最近一次派工的进度和验收结论。',
    );
    expect(repository.groupPostCalls.single['forceDispatch'], false);
    expect(repository.groupPostCalls.single['branchContext'], '');
    expect(
      repository.groupPostCalls.single['context'],
      {'tool_action': 'acceptance_followup'},
    );
  });

  testWidgets('AI group create keeps Android required Xiaoc member', (
    WidgetTester tester,
  ) async {
    final repository = _FakeRealtimeRepository();
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: AiGroupCreateScreen(repository: repository),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('发起群聊'), findsOneWidget);
    expect(find.text('小C助理'), findsWidgets);
    expect(find.text('超级员工-Codex'), findsOneWidget);
    expect(find.text('超级员工-Cursor'), findsOneWidget);
    expect(find.text('超级员工-Claude'), findsOneWidget);
    expect(find.text('超级员工-Trae'), findsOneWidget);
    expect(find.text('静态站内容编辑员'), findsOneWidget);
    expect(find.text('固定'), findsOneWidget);
    expect(find.text('完成(1)'), findsOneWidget);
    expect(repository.employeeLoads, 1);
    expect(repository.candidateLoads, 0);

    await tester.tap(find.text('静态站内容编辑员'));
    await tester.pumpAndSettle();

    expect(find.text('完成(2)'), findsOneWidget);
  });

  testWidgets('fixed partner profile matches Android super employee profile', (
    WidgetTester tester,
  ) async {
    tester.view.devicePixelRatio = 1;
    tester.view.physicalSize = const Size(430, 1800);
    addTearDown(tester.view.resetDevicePixelRatio);
    addTearDown(tester.view.resetPhysicalSize);

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: const FixedPartnerProfileScreen(kind: FixedPartnerKind.codex),
      ),
    );

    expect(find.text('超级员工-Codex'), findsOneWidget);
    expect(find.text('昵称：全设备协同 · 排比派工'), findsOneWidget);
    expect(find.text('AI号：XCAGI-CODEX'), findsOneWidget);
    expect(find.text('伙伴资料'), findsOneWidget);
    expect(find.text('AI交流圈'), findsOneWidget);
    expect(find.text('基础功能'), findsOneWidget);
    expect(find.text('发消息'), findsOneWidget);
    expect(find.byKey(const ValueKey('we_top_bar_divider_')), findsNothing);
    expect(
      find.byWidgetPredicate(
        (widget) =>
            widget is Icon &&
            widget.icon == Icons.forum &&
            widget.color == AppTheme.momentAccent,
      ),
      findsOneWidget,
    );
    expect(
      FixedPartnerProfileSpec.fromKind(FixedPartnerKind.claude).avatarColor,
      AppTheme.momentAccent,
    );
    expect(
      FixedPartnerProfileSpec.kindForConversation(
        const ConversationItem(
          id: 'pinned:trae',
          type: ConversationType.pinnedTrae,
          title: '超级员工-Trae',
          subtitle: '全设备协同 · Trae',
          timestampText: '',
          isPinned: true,
        ),
      ),
      isNull,
    );
  });

  testWidgets('fixed partner profile follows Android dark theme tokens', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        darkTheme: AppTheme.dark(),
        themeMode: ThemeMode.dark,
        home: const FixedPartnerProfileScreen(kind: FixedPartnerKind.codex),
      ),
    );

    final colors = AppTheme.colors(
      tester.element(find.byType(FixedPartnerProfileScreen)),
    );
    final scaffold = tester.widget<Scaffold>(find.byType(Scaffold));
    final title = tester.widget<Text>(find.text('超级员工-Codex'));
    final forumIcon = tester.widget<Icon>(
      find.byWidgetPredicate(
        (widget) =>
            widget is Icon &&
            widget.icon == Icons.forum &&
            widget.color == colors.momentAccent,
      ),
    );

    expect(scaffold.backgroundColor, colors.page);
    expect(title.style?.color, colors.textPrimary);
    expect(forumIcon.color, colors.momentAccent);
  });

  testWidgets('profile tab matches Android current profile shell', (
    WidgetTester tester,
  ) async {
    final api = _FakeProfileApi(
      profilePage: const MobileProfilePageConfig(
        enabled: true,
        revision: 'test',
        heroVariant: 'glass',
        headline: '个人资料 · 软件内更新',
        subtitle: '账号、员工体系、工作台与执行端状态统一管理',
        statusReady: '资料、头像和工作台状态已同步',
        statusSyncing: '正在同步你的资料与工作台状态',
        primaryChip: '管理员账号',
        secondaryChip: '服务器中继 · 电脑执行端',
        accent: 'indigo',
      ),
    );
    tester.view.devicePixelRatio = 1;
    tester.view.physicalSize = const Size(430, 1800);
    addTearDown(tester.view.resetDevicePixelRatio);
    addTearDown(tester.view.resetPhysicalSize);

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: Scaffold(body: ProfileScreen(api: api)),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('个人'), findsOneWidget);
    expect(
      find.byKey(const ValueKey('we_top_bar_divider_个人')),
      findsOneWidget,
    );
    expect(find.text('admin'), findsOneWidget);
    expect(find.text('个人资料 · 软件内更新'), findsOneWidget);
    expect(find.text('账号、员工体系、工作台与执行端状态统一管理'), findsOneWidget);
    expect(find.text('资料、头像和工作台状态已同步'), findsOneWidget);
    expect(find.text('账户余额'), findsOneWidget);
    expect(find.text('10,070.30'), findsOneWidget);
    expect(find.text('扫码绑定'), findsOneWidget);
    expect(find.text('服务'), findsOneWidget);
    expect(find.text('设置'), findsOneWidget);
    expect(find.text('关于'), findsOneWidget);
    expect(find.text(MobileAndroidBuild.profileVersionText), findsOneWidget);
    expect(find.text('蜀ICP备2026014056号-3A'), findsOneWidget);
    final heroDecoration = tester
        .widget<Container>(find.byKey(const ValueKey('profile_hero_card')))
        .decoration! as BoxDecoration;
    final heroGradient = heroDecoration.gradient! as LinearGradient;
    expect(
      heroGradient.colors.last,
      Color.alphaBlend(
        AppTheme.light().colorScheme.secondaryContainer.withAlpha(70),
        AppTheme.surface,
      ),
    );
    expect(
      (tester
              .widget<Container>(
                find.byKey(const ValueKey('profile_avatar_frame')),
              )
              .decoration! as BoxDecoration)
          .color,
      AppTheme.surface,
    );
    expect(
      (tester
              .widget<Container>(
                find.byKey(const ValueKey('profile_avatar_badge_accent')),
              )
              .decoration! as BoxDecoration)
          .color,
      AppTheme.brand,
    );
    expect(
      tester
          .widget<Icon>(find.byKey(const ValueKey('profile_hero_chevron')))
          .color,
      AppTheme.textSecondary,
    );
    final walletDecoration = tester
        .widget<Container>(find.byKey(const ValueKey('profile_wallet_card')))
        .decoration! as BoxDecoration;
    final walletGradient = walletDecoration.gradient! as LinearGradient;
    expect(walletGradient.colors, [AppTheme.brand, AppTheme.brandGradientEnd]);
    expect(
      tester
          .widget<Icon>(find.byKey(const ValueKey('we_cell_icon_扫码绑定')))
          .color,
      AppTheme.light().colorScheme.secondary,
    );
    expect(
      (tester
              .widget<Container>(
                find.byKey(const ValueKey('we_cell_icon_box_扫码绑定')),
              )
              .decoration! as BoxDecoration)
          .color,
      AppTheme.light().colorScheme.secondaryContainer,
    );
    expect(
      tester.widget<Icon>(find.byKey(const ValueKey('we_cell_icon_服务'))).color,
      AppTheme.light().colorScheme.secondary,
    );
    expect(
      (tester
              .widget<Container>(
                find.byKey(const ValueKey('we_cell_icon_box_服务')),
              )
              .decoration! as BoxDecoration)
          .color,
      AppTheme.light().colorScheme.secondaryContainer,
    );
    expect(
      tester.widget<Icon>(find.byKey(const ValueKey('we_cell_arrow_服务'))).color,
      AppTheme.light().colorScheme.onSurfaceVariant.withValues(alpha: 0.62),
    );

    await tester.tap(find.text('服务'));
    await tester.pumpAndSettle();
    expect(find.text('安全'), findsOneWidget);
    expect(find.text('检查更新'), findsOneWidget);
    await tester.tap(find.byIcon(Icons.arrow_back).last);
    await tester.pumpAndSettle();

    await tester.tap(find.text('扫码绑定'));
    await tester.pumpAndSettle();

    expect(find.text('Agent 远程控制'), findsOneWidget);
    expect(find.image(const AssetImage(appLauncherIconAsset)), findsOneWidget);
    expect(find.text('XCAGI 手机控制端'), findsOneWidget);
    expect(find.text('扫描绑定'), findsOneWidget);
    expect(find.text('返回'), findsWidgets);
  });

  testWidgets('profile tab follows Android dark theme tokens', (
    WidgetTester tester,
  ) async {
    final api = _FakeProfileApi(
      profilePage: const MobileProfilePageConfig(
        enabled: true,
        revision: 'dark-test',
        heroVariant: 'glass',
        headline: '个人资料 · 软件内更新',
        subtitle: '账号、员工体系、工作台与执行端状态统一管理',
        statusReady: '资料、头像和工作台状态已同步',
        statusSyncing: '正在同步你的资料与工作台状态',
        primaryChip: '管理员账号',
        secondaryChip: '服务器中继 · 电脑执行端',
        accent: 'indigo',
      ),
    );

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        darkTheme: AppTheme.dark(),
        themeMode: ThemeMode.dark,
        home: Scaffold(body: ProfileScreen(api: api)),
      ),
    );
    await tester.pumpAndSettle();

    final colors = AppTheme.colors(tester.element(find.byType(ProfileScreen)));
    final topBar = tester.widget<Container>(
      find.byKey(const ValueKey('we_top_bar_surface_个人')),
    );
    final heroDecoration = tester
        .widget<Container>(find.byKey(const ValueKey('profile_hero_card')))
        .decoration! as BoxDecoration;
    final heroGradient = heroDecoration.gradient! as LinearGradient;
    final avatarFrame = tester
        .widget<Container>(find.byKey(const ValueKey('profile_avatar_frame')))
        .decoration! as BoxDecoration;
    final avatarBadge = tester
        .widget<Container>(
          find.byKey(const ValueKey('profile_avatar_badge_accent')),
        )
        .decoration! as BoxDecoration;
    final walletDecoration = tester
        .widget<Container>(find.byKey(const ValueKey('profile_wallet_card')))
        .decoration! as BoxDecoration;
    final walletGradient = walletDecoration.gradient! as LinearGradient;
    final chevron = tester.widget<Icon>(
      find.byKey(const ValueKey('profile_hero_chevron')),
    );

    expect(topBar.color, colors.surface);
    expect(heroGradient.colors.first, colors.surface);
    expect(avatarFrame.color, colors.surface);
    expect(avatarBadge.color, colors.brand);
    expect(walletGradient.colors, [colors.brand, colors.brandGradientEnd]);
    expect(chevron.color, colors.textSecondary);
  });

  testWidgets('profile solid hero mirrors Android accent chrome', (
    WidgetTester tester,
  ) async {
    final api = _FakeProfileApi(
      profilePage: const MobileProfilePageConfig(
        enabled: true,
        revision: 'solid-test',
        heroVariant: 'solid',
        headline: '',
        subtitle: '',
        statusReady: '',
        statusSyncing: '',
        primaryChip: '管理员账号',
        secondaryChip: '服务器中继 · 电脑执行端',
        accent: 'purple',
      ),
    );

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: Scaffold(body: ProfileScreen(api: api)),
      ),
    );
    await tester.pumpAndSettle();

    final heroDecoration = tester
        .widget<Container>(find.byKey(const ValueKey('profile_hero_card')))
        .decoration! as BoxDecoration;
    final heroGradient = heroDecoration.gradient! as LinearGradient;
    expect(heroGradient.colors[0], AppTheme.brandGradientEnd);
    expect(
      heroGradient.colors[1],
      AppTheme.brandGradientEnd.withValues(alpha: 0.82),
    );
    expect(heroGradient.colors[2], AppTheme.light().colorScheme.tertiary);
    expect(
      (tester
              .widget<Container>(
                find.byKey(const ValueKey('profile_avatar_frame')),
              )
              .decoration! as BoxDecoration)
          .color,
      Colors.white.withValues(alpha: 0.92),
    );
    expect(
      (tester
              .widget<Container>(
                find.byKey(const ValueKey('profile_avatar_badge_shell')),
              )
              .decoration! as BoxDecoration)
          .color,
      Colors.white.withValues(alpha: 0.92),
    );
    expect(
      (tester
              .widget<Container>(
                find.byKey(const ValueKey('profile_avatar_badge_accent')),
              )
              .decoration! as BoxDecoration)
          .color,
      AppTheme.brandGradientEnd,
    );
    expect(
      tester
          .widget<Icon>(find.byKey(const ValueKey('profile_hero_chevron')))
          .color,
      Colors.white.withValues(alpha: 0.78),
    );
  });

  testWidgets('profile card opens Android profile editor dialog', (
    WidgetTester tester,
  ) async {
    final api = _FakeProfileApi();
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: Scaffold(body: ProfileScreen(api: api)),
      ),
    );
    await tester.pumpAndSettle();

    await tester.tap(find.text('个人资料与工作身份'));
    await tester.pumpAndSettle();

    expect(find.text('个人资料'), findsWidgets);
    expect(find.text('更换头像'), findsOneWidget);
    expect(find.text('移除'), findsOneWidget);
    expect(find.text('昵称'), findsOneWidget);
    expect(find.text('保存'), findsOneWidget);
    expect(find.text('取消'), findsOneWidget);
    expect(find.byType(WeField), findsOneWidget);

    await tester.enterText(find.byType(TextField).last, 'admin-updated');
    await tester.pump();
    await tester.tap(find.text('保存'));
    await tester.pumpAndSettle();

    expect(find.text('admin-updated'), findsOneWidget);
    expect(find.text('资料已保存'), findsOneWidget);
    expect(api.localProfileSaves, [
      {'displayName': 'admin-updated', 'avatarSource': ''},
    ]);
    expect(api.session.username, 'admin-updated');
    expect(api.session.localAvatarSource, '');
  });

  testWidgets('profile tab uses Android local session profile before remote me',
      (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: Scaffold(
          body: ProfileScreen(
            api: _FakeProfileApi(
              session: const MobileSessionData(
                username: 'local-admin',
                accountKind: 'enterprise',
                localAvatarSource: '/tmp/local-avatar.png',
                fhdHost: '10.0.0.2:5112',
                serverMode: 'lan',
              ),
            ),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('local-admin'), findsOneWidget);
    expect(find.text('企业账号'), findsWidgets);
    expect(find.text('Agent 控制 · 10.0.0.2:5112'), findsWidgets);
  });

  testWidgets('profile tab uses Android cached wallet before remote refresh', (
    WidgetTester tester,
  ) async {
    final api = _SlowWalletProfileApi(
      session: const MobileSessionData(
        username: 'admin',
        accountKind: 'admin',
        walletBalanceJson:
            '{"balance":88,"currency":"CNY","membership_level":"pro","experience":12,"byok_configured":true,"byok_count":2,"synced":true,"message":""}',
      ),
    );

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: Scaffold(body: ProfileScreen(api: api)),
      ),
    );
    await tester.pump();
    await tester.pump();

    expect(find.text('88.00'), findsOneWidget);
    expect(find.text('pro'), findsOneWidget);
    expect(find.text('12'), findsOneWidget);
    expect(find.text('已开通'), findsOneWidget);
    expect(api.walletLoads, 1);

    api.remoteWallet.complete(
      const WalletBalanceData(
        balance: 99.5,
        currency: 'CNY',
        membershipLevel: 'vip',
        experience: 24,
        byokConfigured: false,
        byokCount: 0,
        synced: true,
        message: '',
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('99.50'), findsOneWidget);
    expect(find.text('vip'), findsOneWidget);
    expect(find.text('24'), findsOneWidget);
    final cachedWallet = WalletBalanceData.fromJson(
      Map<String, Object?>.from(
          jsonDecode(api.session.walletBalanceJson) as Map),
    );
    expect(cachedWallet.balance, 99.5);
    expect(cachedWallet.membershipLevel, 'vip');
  });

  testWidgets('profile delete account uses Android password confirm dialog', (
    WidgetTester tester,
  ) async {
    tester.view.devicePixelRatio = 1;
    tester.view.physicalSize = const Size(430, 1800);
    addTearDown(tester.view.resetDevicePixelRatio);
    addTearDown(tester.view.resetPhysicalSize);

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: const Scaffold(body: ProfileScreen()),
      ),
    );

    await tester.tap(find.text('注销账号'));
    await tester.pumpAndSettle();

    expect(find.text('注销账号'), findsWidgets);
    expect(find.text('注销后无法恢复，请确认密码。'), findsOneWidget);
    expect(find.text('密码'), findsOneWidget);
    expect(find.text('确认注销'), findsOneWidget);
    expect(find.text('取消'), findsOneWidget);
    expect(find.byType(WeField), findsOneWidget);
    expect(tester.widget<TextField>(find.byType(TextField).last).obscureText,
        isTrue);
    final confirmButton = tester.widget<TextButton>(
      find.ancestor(
        of: find.text('确认注销'),
        matching: find.byType(TextButton),
      ),
    );
    expect(confirmButton.onPressed, isNotNull);
  });

  testWidgets('profile delete account success follows Android logout flow', (
    WidgetTester tester,
  ) async {
    final api = _FakeProfileApi(
      session: const MobileSessionData(
        accessToken: 'access',
        refreshToken: 'refresh',
        sessionId: 'session',
        username: 'admin',
        accountKind: 'admin',
        userId: 7,
        marketAccessToken: 'market',
        relayDesktopId: 'relay-1',
        relayBaseUrl: 'https://xiu-ci.com/fhd-api',
        localBaseUrl: 'http://192.168.31.8:5112/fhd-api',
        setupComplete: true,
        savedUsername: 'remembered-admin',
        savedPassword: 'secret',
        rememberPassword: true,
        autoLogin: true,
        walletBalanceJson: '{"balance":88}',
        cachedChatMessages: {
          'pinned:codex': [
            {'id': 'cache-1', 'body': '清理'},
          ],
        },
      ),
    );
    tester.view.devicePixelRatio = 1;
    tester.view.physicalSize = const Size(430, 1800);
    addTearDown(tester.view.resetDevicePixelRatio);
    addTearDown(tester.view.resetPhysicalSize);

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: Scaffold(body: ProfileScreen(api: api)),
      ),
    );

    await tester.scrollUntilVisible(find.text('注销账号'), 360);
    await tester.tap(find.text('注销账号'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField).last, 'secret');
    await tester.pump();
    await tester.tap(find.text('确认注销'));
    await tester.pumpAndSettle();

    expect(api.deletePasswords, ['secret']);
    expect(api.session.accessToken, '');
    expect(api.session.refreshToken, '');
    expect(api.session.sessionId, '');
    expect(api.session.username, '');
    expect(api.session.accountKind, '');
    expect(api.session.userId, 0);
    expect(api.session.marketAccessToken, '');
    expect(api.session.relayDesktopId, '');
    expect(api.session.relayBaseUrl, '');
    expect(api.session.localBaseUrl, '');
    expect(api.session.setupComplete, isFalse);
    expect(api.session.savedUsername, 'remembered-admin');
    expect(api.session.savedPassword, 'secret');
    expect(api.session.rememberPassword, isTrue);
    expect(api.session.autoLogin, isFalse);
    expect(api.session.walletBalanceJson, '');
    expect(api.session.cachedChatMessages, isEmpty);
    expect(find.text('账号已成功注销'), findsOneWidget);
    expect(find.text('密码登录'), findsWidgets);
  });

  testWidgets('profile logout clears Android active auth before login route', (
    WidgetTester tester,
  ) async {
    final api = _FakeProfileApi(
      session: const MobileSessionData(
        accessToken: 'access',
        refreshToken: 'refresh',
        sessionId: 'session',
        username: 'admin',
        accountKind: 'admin',
        userId: 7,
        marketAccessToken: 'market',
        setupComplete: true,
        savedUsername: 'remembered-admin',
        savedPassword: 'secret',
        rememberPassword: true,
        autoLogin: true,
        walletBalanceJson: '{"balance":88}',
      ),
    );
    tester.view.devicePixelRatio = 1;
    tester.view.physicalSize = const Size(430, 1800);
    addTearDown(tester.view.resetDevicePixelRatio);
    addTearDown(tester.view.resetPhysicalSize);

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: Scaffold(body: ProfileScreen(api: api)),
      ),
    );

    await tester.scrollUntilVisible(find.text('退出登录'), 360);
    await tester.tap(find.text('退出登录'));
    await tester.pumpAndSettle();

    expect(api.session.accessToken, '');
    expect(api.session.refreshToken, '');
    expect(api.session.sessionId, '');
    expect(api.session.username, '');
    expect(api.session.accountKind, '');
    expect(api.session.marketAccessToken, '');
    expect(api.session.setupComplete, isFalse);
    expect(api.session.savedUsername, 'remembered-admin');
    expect(api.session.savedPassword, 'secret');
    expect(api.session.rememberPassword, isTrue);
    expect(api.session.autoLogin, isFalse);
    expect(api.session.walletBalanceJson, '');
    expect(find.text('密码登录'), findsWidgets);
  });

  testWidgets('profile delete account failure uses Android error wording', (
    WidgetTester tester,
  ) async {
    final api = _FakeProfileApi(deleteError: '注销失败，请检查网络后重试');
    tester.view.devicePixelRatio = 1;
    tester.view.physicalSize = const Size(430, 1800);
    addTearDown(tester.view.resetDevicePixelRatio);
    addTearDown(tester.view.resetPhysicalSize);

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: Scaffold(body: ProfileScreen(api: api)),
      ),
    );

    await tester.scrollUntilVisible(find.text('注销账号'), 360);
    await tester.tap(find.text('注销账号'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField).last, 'secret');
    await tester.pump();
    await tester.tap(find.text('确认注销'));
    await tester.pumpAndSettle();

    expect(api.deletePasswords, ['secret']);
    expect(find.text('注销失败，请检查网络后重试'), findsOneWidget);
    expect(find.text('密码登录'), findsNothing);
  });

  testWidgets('connect page matches Android profile binding interstitial', (
    WidgetTester tester,
  ) async {
    var scanned = false;

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: ConnectScreen(
          fromProfile: true,
          onScan: () => scanned = true,
        ),
      ),
    );

    expect(find.text('Agent 远程控制'), findsOneWidget);
    expect(
      find.byKey(const ValueKey('we_top_bar_divider_Agent 远程控制')),
      findsOneWidget,
    );
    expect(find.text('XCAGI 手机控制端'), findsOneWidget);
    final connectTitle = tester.widget<Text>(
      find.byKey(const ValueKey('connect_title')),
    );
    expect(connectTitle.style?.fontSize, 18);
    expect(connectTitle.style?.fontWeight, FontWeight.w600);
    expect(
      find.text('绑定服务器后台、企业工作台或电脑执行端后，手机可远程调动员工和 Codex。'),
      findsOneWidget,
    );
    final connectDescription = tester.widget<Text>(
      find.byKey(const ValueKey('connect_description')),
    );
    expect(connectDescription.style?.fontSize, 14);
    expect(connectDescription.style?.fontWeight, FontWeight.w400);
    expect(find.text('扫描绑定'), findsOneWidget);
    expect(find.text('返回'), findsWidgets);
    expect(
      tester
          .getSize(find.byKey(const ValueKey('connect_primary_button')))
          .height,
      48,
    );
    expect(
      (tester
              .widget<Container>(
                find.byKey(const ValueKey('connect_primary_button')),
              )
              .decoration! as BoxDecoration)
          .borderRadius,
      BorderRadius.circular(8),
    );
    final secondaryButton = tester.widget<Container>(
      find.byKey(const ValueKey('connect_secondary_button')),
    );
    final secondaryDecoration = secondaryButton.decoration! as BoxDecoration;
    expect(
        tester
            .getSize(find.byKey(const ValueKey('connect_secondary_button')))
            .height,
        48);
    expect(secondaryDecoration.borderRadius, BorderRadius.circular(8));
    expect(secondaryDecoration.border?.top.color, AppTheme.divider);
    final secondaryText = tester.widget<Text>(find.text('返回').first);
    expect(secondaryText.style?.fontSize, 15);

    await tester.tap(find.text('扫描绑定'));
    await tester.pump();

    expect(scanned, isTrue);
  });

  testWidgets('connect page follows Android dark theme tokens', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        darkTheme: AppTheme.dark(),
        themeMode: ThemeMode.dark,
        home: const ConnectScreen(fromProfile: true),
      ),
    );

    final colors = AppTheme.colors(tester.element(find.byType(ConnectScreen)));
    final scaffold = tester.widget<Scaffold>(find.byType(Scaffold));
    final topBar = tester.widget<Container>(
      find.byKey(const ValueKey('we_top_bar_surface_Agent 远程控制')),
    );
    final title = tester.widget<Text>(
      find.byKey(const ValueKey('connect_title')),
    );
    final description = tester.widget<Text>(
      find.byKey(const ValueKey('connect_description')),
    );
    final secondary = tester.widget<Container>(
      find.byKey(const ValueKey('connect_secondary_button')),
    );
    final secondaryDecoration = secondary.decoration! as BoxDecoration;

    expect(scaffold.backgroundColor, colors.page);
    expect(topBar.color, colors.surface);
    expect(title.style?.color, colors.textPrimary);
    expect(description.style?.color, colors.textSecondary);
    expect(secondaryDecoration.border?.top.color, colors.divider);
  });

  testWidgets('chat top more opens Android fixed partner profile', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: ChatScreen(
          conversation: demoConversations[1],
          initialMessages: const [],
        ),
      ),
    );

    await tester.tap(find.byTooltip('更多'));
    await tester.pumpAndSettle();

    expect(find.text('AI号：XCAGI-CODEX'), findsOneWidget);
    expect(find.text('伙伴资料'), findsOneWidget);
  });

  testWidgets('super employee chat shows Android CLI switch card', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: ChatScreen(
          conversation: demoConversations[1],
          initialMessages: const [],
        ),
      ),
    );

    expect(find.byKey(const ValueKey('super_dev_cli_model_switch_card')),
        findsOneWidget);
    expect(find.text('超级开发组 · CLI'), findsOneWidget);
    expect(find.text('Codex'), findsOneWidget);
    expect(find.text('Cursor'), findsOneWidget);
    expect(find.text('Claude'), findsOneWidget);
    expect(find.text('Trae'), findsOneWidget);

    await tester.tap(
      find.byKey(const ValueKey('super_dev_cli_option_pinned:cursor')),
    );
    await tester.pumpAndSettle();

    expect(find.text('超级员工-Cursor'), findsWidgets);
    expect(find.byKey(const ValueKey('super_dev_cli_model_switch_card')),
        findsOneWidget);
  });

  testWidgets('chat detail resolves employee profile from Android modInfos', (
    WidgetTester tester,
  ) async {
    const employee = AiEmployeeProfile(
      modId: 'avatar-mod',
      modName: '头像员工包',
      modDescription: '生成头像',
      modVersion: '1.0.0',
      modAuthor: 'XCAGI',
      industryName: '视觉',
      employeeId: 'avatar-generation-employee',
      name: '头像生成员工',
      title: '头像设计师',
      summary: '当前员工资料',
      apiBasePath: '/api/avatar',
      phoneChannel: 'mobile-chat',
      workflowPlaceholder: false,
      profileSource: 'market',
      marketConnected: true,
      marketPkgId: 'avatar-generation-employee',
      marketVersion: '1.0.0',
      marketAuthor: 'XCAGI',
      marketMaterialCategory: 'AI 员工',
      marketLicenseScope: 'enterprise',
      marketSecurityLevel: 'standard',
      avatarUrl: 'https://cdn.example.com/current-avatar.png',
    );
    final repository = _FakeChatEmployeeRepository(const [employee]);

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: ChatScreen(
          conversation: const ConversationItem(
            id: 'employee:avatar-mod:avatar-generation-employee',
            type: ConversationType.aiTask,
            title: '旧会话标题',
            subtitle: '旧摘要',
            timestampText: '刚刚',
          ),
          repository: repository,
          initialMessages: const [
            ChatMessage(
              id: 'employee-reply',
              conversationId: 'employee:avatar-mod:avatar-generation-employee',
              role: ChatRole.assistant,
              body: '我来生成头像',
              timeText: '刚刚',
            ),
          ],
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('头像生成员工'), findsOneWidget);
    expect(find.text('旧会话标题'), findsNothing);
    final employeeAvatars = tester
        .widgetList<AppAvatar>(
          find.byType(AppAvatar),
        )
        .where(
          (avatar) =>
              avatar.imageSource ==
              'https://cdn.example.com/current-avatar.png',
        );
    expect(employeeAvatars, isNotEmpty);
    expect(employeeAvatars.first.fallback,
        AppAvatarFallback.empAvatarGenerationEmployee);
    expect(repository.employeeLoads, 1);

    await tester.tap(find.byTooltip('更多'));
    await tester.pumpAndSettle();

    expect(find.text('当前员工资料'), findsOneWidget);
    expect(find.text('来源：AI市场 · 头像员工包'), findsOneWidget);
  });

  testWidgets('chat detail shows Android bubble timestamps', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: ChatScreen(
          conversation: demoConversations[1],
          initialMessages: const [
            ChatMessage(
              id: 'user-ts',
              conversationId: 'pinned:codex',
              role: ChatRole.user,
              body: '我不是用的 fastapi 吗',
              timeText: '2000-01-02T05:45:00',
            ),
            ChatMessage(
              id: 'assistant-ts',
              conversationId: 'pinned:codex',
              role: ChatRole.assistant,
              body: '思考中...',
              timeText: '05:46',
            ),
            ChatMessage(
              id: 'assistant-sending',
              conversationId: 'pinned:codex',
              role: ChatRole.assistant,
              body: '正在处理',
              timeText: '不应显示',
              status: ChatDeliveryStatus.sending,
            ),
          ],
        ),
      ),
    );

    expect(find.text('1/2 05:45'), findsOneWidget);
    expect(find.text('05:46'), findsOneWidget);
    expect(find.text('不应显示'), findsNothing);
  });

  testWidgets(
      'chat detail uses Android composer and hides debug endpoint strip', (
    WidgetTester tester,
  ) async {
    tester.view.devicePixelRatio = 1;
    tester.view.physicalSize = const Size(430, 1800);
    addTearDown(tester.view.resetDevicePixelRatio);
    addTearDown(tester.view.resetPhysicalSize);

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: ChatScreen(
          conversation: demoConversations[1],
          initialMessages: const [],
        ),
      ),
    );

    expect(find.text('超级员工-Codex'), findsWidgets);
    expect(find.byIcon(Icons.mic), findsOneWidget);
    expect(find.byIcon(Icons.add), findsOneWidget);
    expect(find.text('发送'), findsNothing);
    expect(find.textContaining('api/mobile'), findsNothing);
    final typography = AppTheme.light().textTheme;
    final composer = tester.widget<Container>(
      find.byKey(const ValueKey('chat_composer_surface')),
    );
    final composerDecoration = composer.decoration as BoxDecoration;
    final composerBorder = composerDecoration.border as Border;
    expect(composerDecoration.color, AppTheme.surface);
    expect(
        composerBorder.top.color, AppTheme.light().colorScheme.outlineVariant);
    expect(composerBorder.top.width, 0.5);
    final textField = tester.widget<TextField>(find.byType(TextField));
    expect(textField.style?.fontSize, typography.bodyMedium?.fontSize);
    expect(textField.style?.height, typography.bodyMedium?.height);
    expect(textField.decoration?.hintStyle?.fontSize,
        typography.bodyMedium?.fontSize);
    expect(
        textField.decoration?.hintStyle?.height, typography.bodyMedium?.height);

    await tester.enterText(find.byType(TextField), '继续');
    await tester.pump();

    expect(find.text('发送'), findsOneWidget);
    final sendText = tester.widget<Text>(find.text('发送'));
    expect(sendText.style?.fontSize, 15);
    expect(sendText.style?.height, typography.labelLarge?.height);
    expect(sendText.style?.fontWeight, FontWeight.w500);

    await tester.tap(find.byTooltip('更多工具'));
    await tester.pump();

    expect(find.text('新建对话'), findsOneWidget);
    expect(find.text('OCR 识别'), findsOneWidget);
    expect(find.text('语音输入'), findsOneWidget);
    expect(find.text('任务派工'), findsOneWidget);
    expect(find.text('验收回访'), findsOneWidget);
    expect(find.text('问题修复'), findsOneWidget);
    final toolPanel = tester.widget<Padding>(
      find.byKey(const ValueKey('chat_tool_card_panel')),
    );
    expect(toolPanel.padding, const EdgeInsets.fromLTRB(12, 8, 12, 20));
    expect(
      tester.getSize(find.byKey(const ValueKey('chat_tool_card_任务派工'))).height,
      92,
    );
    expect(
      tester.getSize(find.byKey(const ValueKey('chat_tool_icon_box_任务派工'))),
      const Size(62, 62),
    );
    final taskToolText = tester.widget<Text>(find.text('任务派工'));
    expect(taskToolText.style?.fontSize, typography.labelMedium?.fontSize);
    expect(taskToolText.style?.height, typography.labelMedium?.height);

    await tester.tap(find.text('任务派工'));
    await tester.pump();

    expect(find.text('帮我安排并完成这个任务：继续'), findsOneWidget);
  });

  testWidgets('chat detail streams into Android assistant placeholder bubble', (
    WidgetTester tester,
  ) async {
    final repository = _FakeStreamingChatRepository();

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: ChatScreen(
          conversation: _fakeUnreadConversation,
          repository: repository,
          initialMessages: const [
            ChatMessage(
              id: 'old-1',
              conversationId: 'employee:demo:customer',
              role: ChatRole.assistant,
              body: '上一轮',
              timeText: '刚刚',
            ),
          ],
        ),
      ),
    );

    await tester.enterText(find.byType(TextField), '继续');
    await tester.pump();
    await tester.tap(find.text('发送'));
    await tester.pump();
    await repository.firstToken.future;
    await tester.pump();

    expect(find.text('继续'), findsOneWidget);
    expect(find.textContaining('开始'), findsOneWidget);
    expect(repository.calls.single['body'], '继续');
    expect(repository.calls.single['userId'], 0);
    expect(repository.calls.single['recentMessages'], [
      'assistant:上一轮',
      'user:继续',
    ]);

    repository.finish.complete();
    await tester.pumpAndSettle();

    expect(find.text('开始处理完成'), findsOneWidget);
    expect(find.text('发送失败'), findsNothing);
  });

  testWidgets('chat detail long press supports Android reply and delete', (
    WidgetTester tester,
  ) async {
    final repository = _FakeStreamingChatRepository();

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: ChatScreen(
          conversation: _fakeUnreadConversation,
          repository: repository,
          initialMessages: const [
            ChatMessage(
              id: 'old-1',
              conversationId: 'employee:demo:customer',
              role: ChatRole.assistant,
              body: '上一轮',
              timeText: '刚刚',
            ),
          ],
        ),
      ),
    );

    await tester.longPress(find.text('上一轮'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('引用'));
    await tester.pumpAndSettle();

    expect(find.text('引用 对方：上一轮'), findsOneWidget);

    await tester.enterText(find.byType(TextField), '继续');
    await tester.pump();
    await tester.tap(find.text('发送'));
    await tester.pump();
    await repository.firstToken.future;

    expect(repository.calls.single['body'], '引用「上一轮」\n\n继续');

    repository.finish.complete();
    await tester.pumpAndSettle();

    await tester.longPress(find.text('开始处理完成'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('删除'));
    await tester.pumpAndSettle();

    expect(find.text('开始处理完成'), findsNothing);
  });

  testWidgets('chat detail stop keeps partial Android streaming bubble', (
    WidgetTester tester,
  ) async {
    final repository = _FakeStreamingChatRepository();

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: ChatScreen(
          conversation: _fakeUnreadConversation,
          repository: repository,
          initialMessages: const [],
        ),
      ),
    );

    await tester.enterText(find.byType(TextField), '继续');
    await tester.pump();
    await tester.tap(find.text('发送'));
    await tester.pump();
    await repository.firstToken.future;
    await tester.pump();

    expect(find.text('停止'), findsOneWidget);
    expect(find.textContaining('开始'), findsOneWidget);

    await tester.tap(find.text('停止'));
    await tester.pump();
    final isCancelled =
        repository.calls.single['isCancelled'] as bool Function();
    expect(isCancelled(), isTrue);
    repository.finish.complete();
    await tester.pumpAndSettle();

    expect(find.text('开始处理完成'), findsNothing);
    expect(find.text('发送失败'), findsNothing);
  });

  testWidgets('super employee chat resumes Android inflight relay task', (
    WidgetTester tester,
  ) async {
    final repository = _FakeInflightRelayRepository();

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: ChatScreen(
          conversation: demoConversations[1],
          repository: repository,
          initialMessages: const [],
        ),
      ),
    );

    await tester.pump();
    await repository.firstToken.future;
    await tester.pump();

    expect(find.text('停止'), findsOneWidget);
    expect(find.textContaining('思考中'), findsOneWidget);

    repository.finish.complete('电脑执行端已完成任务。');
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 100));

    expect(find.text('停止'), findsNothing);
    expect(find.text('电脑执行端已完成任务。'), findsOneWidget);
  });

  testWidgets('chat detail failed assistant bubble can resend like Android', (
    WidgetTester tester,
  ) async {
    final repository = _FakeFailThenStreamingRepository();

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: ChatScreen(
          conversation: _fakeUnreadConversation,
          repository: repository,
          initialMessages: const [],
        ),
      ),
    );

    await tester.enterText(find.byType(TextField), '继续');
    await tester.pump();
    await tester.tap(find.text('发送'));
    await tester.pumpAndSettle();

    expect(find.text('发送失败'), findsOneWidget);
    expect(find.text('连接不到电脑执行端，已尝试通过服务器中继，请稍后重试'), findsOneWidget);
    expect(find.textContaining('failed to connect'), findsNothing);
    expect(find.text('重发'), findsOneWidget);

    await tester.tap(find.text('重发'));
    await tester.pumpAndSettle();

    expect(repository.calls, ['继续', '继续']);
    expect(find.text('重发成功'), findsOneWidget);
    expect(find.text('发送失败'), findsNothing);
    expect(find.text('继续'), findsOneWidget);
  });

  testWidgets('super employee chat shows Android git action bar', (
    WidgetTester tester,
  ) async {
    final repository = _FakeRealtimeRepository();
    const branchA = 'super-employee/codex/feature-one';
    const branchB = 'super-employee/codex/fix-two';

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: ChatScreen(
          conversation: demoConversations[1],
          repository: repository,
          initialMessages: const [
            ChatMessage(
              id: 'a1',
              conversationId: 'pinned:codex',
              role: ChatRole.assistant,
              body: '已创建任务分支 $branchA',
              timeText: '刚刚',
            ),
            ChatMessage(
              id: 'a2',
              conversationId: 'pinned:codex',
              role: ChatRole.assistant,
              body: '已创建任务分支 $branchB',
              timeText: '刚刚',
            ),
          ],
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('开发任务分支 · fix-two（点此切换）'), findsOneWidget);
    expect(find.text('查看 diff'), findsOneWidget);
    expect(find.text('合并到主干'), findsOneWidget);
    expect(find.text('丢弃'), findsOneWidget);

    await tester.tap(find.text('开发任务分支 · fix-two（点此切换）'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('feature-one'));
    await tester.pumpAndSettle();

    expect(find.text('开发任务分支 · feature-one（点此切换）'), findsOneWidget);

    await tester.tap(find.text('合并到主干'));
    await tester.pumpAndSettle();

    expect(repository.gitOperations, [
      {'branch': branchA, 'op': 'git.merge'},
    ]);
    expect(find.text('✅ 已合并 $branchA'), findsOneWidget);
  });
}

Future<void> _tapHeaderPlusMenuItem(
  WidgetTester tester,
  String label,
) async {
  await tester.tap(find.byTooltip('更多'));
  await tester.pumpAndSettle();
  await tester.tap(find.text(label));
  await tester.pumpAndSettle();
}

const _fakeGroup = AiGroupConversation(
  id: 'dev',
  name: '超级开发部',
  memberCount: 2,
  preview: '先评估任务，再派给最合适的人。',
  timestampText: '刚刚',
  members: [
    AiGroupMember(
      employeeId: 'xcagi-assistant',
      modId: 'core',
      name: '小C助理',
      summary: '企业 AI 助手',
    ),
    AiGroupMember(
      employeeId: 'site-content-editor',
      modId: 'admin-duty',
      name: '静态站内容编辑员',
      summary: '维护官网内容',
    ),
  ],
);

const _fakeUnreadConversation = ConversationItem(
  id: 'employee:demo:customer',
  type: ConversationType.aiTask,
  title: '客户会话',
  subtitle: '需要跟进',
  timestampText: '刚刚',
  unreadCount: 2,
  isPinned: true,
  isFollowed: true,
  isHidden: false,
);

class _FakeRealtimeRepository extends MobileRepository {
  final List<Map<String, String>> gitOperations = [];
  final List<Map<String, Object?>> groupPostCalls = [];
  var employeeLoads = 0;
  var candidateLoads = 0;

  @override
  Future<MobileMeData> loadMe() async {
    return MobileMeData.adminFallback();
  }

  @override
  Future<List<ChatMessage>> loadInitialMessages(
    ConversationItem conversation,
  ) async {
    return const [];
  }

  @override
  Future<CsInfo> loadCsInfo() async {
    return const CsInfo(
      available: true,
      name: '客服在线',
      online: true,
    );
  }

  @override
  Future<List<CsMessage>> loadCsMessages({String? since}) async {
    return const [
      CsMessage(
        messageId: 'cs-1',
        sender: 'cs',
        body: '欢迎使用专属客服',
        timestamp: '刚刚',
      ),
    ];
  }

  @override
  Future<CsMessageResponse> sendCsMessage(String body) async {
    return const CsMessageResponse(
      messageId: 'cs-2',
      requestId: 7,
      reply: '我来处理',
      backend: 'fake',
      timestamp: '刚刚',
    );
  }

  @override
  Future<List<AiGroupConversation>> loadAiGroups() async {
    return const [_fakeGroup];
  }

  @override
  Future<List<AiEmployeeProfile>> loadAiEmployees() async {
    employeeLoads += 1;
    return adminDutyEmployeeProfiles(const [
      DutyRosterEmployee(
        id: 'site-content-editor',
        label: '静态站内容编辑员',
        summary: '维护官网内容',
      ),
    ]);
  }

  @override
  Future<List<AiGroupCandidate>> loadGroupMemberCandidates() async {
    candidateLoads += 1;
    return const [
      AiGroupCandidate(
        employeeId: 'xcagi-assistant',
        modId: 'core',
        name: '小C助理',
        summary: '企业 AI 助手',
        departmentKey: 'core',
        isSuper: false,
      ),
      AiGroupCandidate(
        employeeId: 'site-content-editor',
        modId: 'admin-duty',
        name: '静态站内容编辑员',
        summary: '维护官网内容',
        departmentKey: 'website',
        isSuper: false,
      ),
    ];
  }

  @override
  Future<AiGroupConversation?> createGroupWithMembers({
    required String name,
    required List<AiGroupCandidate> members,
  }) async {
    return _fakeGroup.copyWith(name: name, memberCount: members.length);
  }

  @override
  Future<List<AiGroupMessage>> loadAiGroupMessages(String groupId) async {
    return const [
      AiGroupMessage(
        id: 'm1',
        groupId: 'dev',
        role: AiGroupMessageRole.ai,
        senderId: 'xcagi-assistant',
        senderName: '小C助理',
        body: '先评估任务，再派给最合适的人。',
        createdAt: '刚刚',
        kind: 'discussion',
      ),
    ];
  }

  @override
  Future<List<GitBranchInfo>> loadGitBranches() async {
    return const [
      GitBranchInfo(
          name: 'feature/android-parity', current: true, remote: false),
    ];
  }

  @override
  Future<AiGroupPostResult> postAiGroupMessage({
    required String groupId,
    required String message,
    List<String> mentions = const [],
    String branchContext = '',
    bool forceDispatch = false,
    Map<String, String> context = const {},
  }) async {
    groupPostCalls.add({
      'groupId': groupId,
      'message': message,
      'mentions': mentions,
      'branchContext': branchContext,
      'forceDispatch': forceDispatch,
      'context': context,
    });
    return AiGroupPostResult(
      group: _fakeGroup,
      messages: [
        AiGroupMessage(
          id: 'user-1',
          groupId: groupId,
          role: AiGroupMessageRole.user,
          senderId: 'user',
          senderName: '我',
          body: message,
          createdAt: '刚刚',
        ),
        const AiGroupMessage(
          id: 'ai-1',
          groupId: 'dev',
          role: AiGroupMessageRole.ai,
          senderId: 'xcagi-assistant',
          senderName: '小C助理',
          body: '收到，开始协作。',
          createdAt: '刚刚',
        ),
      ],
    );
  }

  @override
  Future<AiGroupConversation?> toggleAiGroupPin(String groupId) async {
    return _fakeGroup.copyWith(isPinned: true);
  }

  @override
  Future<AiGroupConversation?> markAiGroupUnread(String groupId) async {
    return _fakeGroup.copyWith(unreadCount: 1);
  }

  @override
  Future<AiGroupConversation?> toggleAiGroupFollowed(String groupId) async {
    return _fakeGroup.copyWith(isFollowed: false);
  }

  @override
  Future<AiGroupConversation?> toggleAiGroupHidden(String groupId) async {
    return _fakeGroup.copyWith(isHidden: true);
  }

  @override
  Future<void> deleteAiGroup(String groupId) async {}

  @override
  Future<String> runGitOperation({
    required String branch,
    required String op,
  }) async {
    gitOperations.add({'branch': branch, 'op': op});
    if (op == 'git.merge') return '✅ 已合并 $branch';
    if (op == 'git.discard') return '已丢弃分支 $branch';
    return 'diff for $branch';
  }
}

class _FakeChatEmployeeRepository extends _FakeRealtimeRepository {
  _FakeChatEmployeeRepository(this.employees);

  final List<AiEmployeeProfile> employees;

  @override
  Future<List<AiEmployeeProfile>> loadAiEmployees() async {
    employeeLoads += 1;
    return employees;
  }
}

class _FakeEmptyThenBranchRepository extends _FakeRealtimeRepository {
  var branchLoads = 0;

  @override
  Future<List<GitBranchInfo>> loadGitBranches() async {
    branchLoads += 1;
    if (branchLoads == 1) return const [];
    return const [
      GitBranchInfo(name: 'feature/refreshed', current: false, remote: true),
    ];
  }
}

class _FakePairingRepository extends MobileRepository {
  _FakePairingRepository({this.failPairing = false});

  final bool failPairing;
  final List<String> pairingCodes = [];

  @override
  Future<void> exchangePairingCode(String raw) async {
    pairingCodes.add(raw);
    if (failPairing) {
      throw const MobileRepositoryException('failed to connect to desktop');
    }
  }
}

class _SlowBusinessRepository extends MobileRepository {
  final shipments = Completer<List<BusinessListItem>>();

  @override
  Future<List<BusinessListItem>> loadShipments() => shipments.future;
}

class _FakeBridgeRepository extends MobileRepository {
  _FakeBridgeRepository(this.items);

  final List<BusinessListItem> items;
  final List<String?> bridgeRequestTypes = [];
  final List<Map<String, Object?>> replies = [];

  @override
  Future<List<BusinessListItem>> loadBridgeRequests({
    String? status,
    String? requestType,
  }) async {
    bridgeRequestTypes.add(requestType);
    return items;
  }

  @override
  Future<void> respondBridgeRequest({
    required int id,
    required String response,
    String respondedBy = 'android',
  }) async {
    replies.add({
      'id': id,
      'response': response,
      'respondedBy': respondedBy,
    });
  }
}

class _FakeStreamingChatRepository extends _FakeRealtimeRepository {
  final firstToken = Completer<void>();
  final finish = Completer<void>();
  final List<Map<String, Object?>> calls = [];

  @override
  Future<String> streamMessage({
    required ConversationItem conversation,
    required String body,
    int userId = 0,
    List<ChatMessage> recentMessages = const [],
    void Function(String token)? onToken,
    bool Function()? isCancelled,
  }) async {
    calls.add({
      'conversationId': conversation.id,
      'body': body,
      'userId': userId,
      'recentMessages': recentMessages
          .map((message) => '${message.role.name}:${message.body}')
          .toList(growable: false),
      'isCancelled': isCancelled,
    });
    onToken?.call('开始');
    if (!firstToken.isCompleted) firstToken.complete();
    await finish.future;
    return '开始处理完成';
  }
}

class _FakeFailThenStreamingRepository extends _FakeRealtimeRepository {
  final calls = <String>[];

  @override
  Future<String> streamMessage({
    required ConversationItem conversation,
    required String body,
    int userId = 0,
    List<ChatMessage> recentMessages = const [],
    void Function(String token)? onToken,
    bool Function()? isCancelled,
  }) async {
    calls.add(body);
    if (calls.length == 1) {
      throw const MobileRepositoryException('failed to connect to desktop');
    }
    onToken?.call('重发');
    return '重发成功';
  }
}

class _FakeInflightRelayRepository extends _FakeRealtimeRepository {
  final firstToken = Completer<void>();
  final finish = Completer<String>();

  @override
  Future<List<ChatMessage>> loadInitialMessages(
    ConversationItem conversation,
  ) async {
    return const [];
  }

  @override
  Future<bool> hasInflightRelay(String conversationId) async {
    return conversationId == PinnedIds.codex;
  }

  @override
  Future<String?> resumeRelayTask({
    required String conversationId,
    void Function(String token)? onToken,
    bool Function()? isCancelled,
  }) async {
    onToken?.call('思考中...');
    if (!firstToken.isCompleted) firstToken.complete();
    return finish.future;
  }
}

class _FakeDiscoverRepository extends MobileRepository {
  _FakeDiscoverRepository(this.menu);

  final List<MobileNavMenuItem> menu;

  @override
  Future<List<MobileNavMenuItem>> loadNavMenu() async => menu;

  @override
  Future<List<AiEmployeeProfile>> loadAiEmployees() async {
    return adminDutyEmployeeProfiles();
  }
}

class _FakeHomeShellRepository extends MobileRepository {
  _FakeHomeShellRepository({
    List<AiEmployeeProfile>? employees,
    this.groups,
    this.account,
    this.accountFromClientSession = false,
    super.client,
  }) : employees = employees ?? adminDutyEmployeeProfiles();

  final List<AiEmployeeProfile> employees;
  final List<AiGroupConversation>? groups;
  final MobileMeData? account;
  final bool accountFromClientSession;
  final List<Map<String, bool>> conversationLoads = [];
  final List<String?> bridgeRequestTypes = [];
  var employeeLoads = 0;
  var accountLoads = 0;

  @override
  Future<List<AiGroupConversation>> loadAiGroups() async {
    final seeded = groups;
    if (seeded != null) return seeded;
    throw const MobileRepositoryException('offline');
  }

  @override
  Future<List<ConversationItem>> loadConversations({
    bool adminMode = true,
    bool enterpriseMode = true,
  }) async {
    conversationLoads.add({
      'adminMode': adminMode,
      'enterpriseMode': enterpriseMode,
    });
    return fallbackConversations(
      adminMode: adminMode,
      enterpriseMode: enterpriseMode,
    );
  }

  @override
  Future<MobileMeData> loadMe() async {
    accountLoads += 1;
    final seeded = account;
    if (seeded != null) return seeded;
    if (accountFromClientSession) return cachedMe();
    return MobileMeData.adminFallback();
  }

  @override
  Future<List<AiEmployeeProfile>> loadAiEmployees() async {
    employeeLoads += 1;
    return employees;
  }

  @override
  Future<List<ChatMessage>> loadInitialMessages(
    ConversationItem conversation,
  ) async {
    return const [];
  }

  @override
  Future<List<BusinessListItem>> loadBridgeRequests({
    String? status,
    String? requestType,
  }) async {
    bridgeRequestTypes.add(requestType);
    return const [
      BusinessListItem(
        id: '11',
        title: '需要企业客服跟进',
        subtitle: 'pending',
        payload: {
          'source_instance_name': '手机端客户',
          'description': '需要企业客服跟进',
          'status': 'pending',
        },
      ),
    ];
  }

  @override
  Future<List<AiGroupMessage>> loadAiGroupMessages(String groupId) async {
    return [
      AiGroupMessage(
        id: 'home-shell-$groupId-message',
        groupId: groupId,
        role: AiGroupMessageRole.ai,
        senderId: 'xcagi-assistant',
        senderName: '小C助理',
        body: '先评估任务，再派给最合适的人。',
        createdAt: '刚刚',
        kind: 'discussion',
      ),
    ];
  }

  @override
  Future<List<GitBranchInfo>> loadGitBranches() async => const [];

  @override
  Future<List<AiGroupCandidate>> loadGroupMemberCandidates() async => const [];
}

class _SlowMeHomeShellRepository extends _FakeHomeShellRepository {
  _SlowMeHomeShellRepository({required super.client});

  final remoteMe = Completer<MobileMeData>();
  var loadMeCalls = 0;

  @override
  Future<MobileMeData> loadMe() {
    loadMeCalls += 1;
    return remoteMe.future;
  }
}

class _CachedFirstHomeShellRepository extends MobileRepository {
  _CachedFirstHomeShellRepository()
      : super(
          client: _FakeProfileApi(
            session: const MobileSessionData(
              username: 'admin',
              accountKind: 'enterprise',
              userId: 1,
              cachedModInfos: [
                {
                  'id': 'cached-avatar-mod',
                  'name': '缓存头像包',
                  'workflow_employees': [
                    {
                      'id': 'cached-avatar-employee',
                      'label': '缓存头像员工',
                      'panel_summary': '来自缓存的员工资料',
                      'phone_channel': 'mobile-chat',
                    },
                  ],
                },
              ],
              conversationListStates: {
                'employee:cached-avatar-mod:cached-avatar-employee': {
                  'last_message_preview': '我: 先看缓存',
                  'last_message_at': 1719820800000,
                },
              },
            ),
          ),
        );

  final remoteConversations = Completer<List<ConversationItem>>();
  var loadConversationCalls = 0;

  @override
  Future<List<AiGroupConversation>> loadAiGroups() async {
    return const [];
  }

  @override
  Future<List<ConversationItem>> loadConversations({
    bool adminMode = true,
    bool enterpriseMode = true,
  }) {
    loadConversationCalls += 1;
    return remoteConversations.future;
  }

  @override
  Future<MobileMeData> loadMe() => cachedMe();
}

class _FakeEmployeesRepository extends MobileRepository {
  _FakeEmployeesRepository(this.employees);

  final List<AiEmployeeProfile> employees;
  var employeeLoads = 0;

  @override
  Future<List<AiEmployeeProfile>> loadAiEmployees() async {
    employeeLoads += 1;
    return employees;
  }
}

class _FakeConversationActionRepository extends _FakeRealtimeRepository {
  final List<String> actions = [];

  @override
  Future<void> markConversationRead(String conversationId) async {
    actions.add('conversation-read:$conversationId');
  }

  @override
  Future<void> markConversationUnread(String conversationId) async {
    actions.add('conversation-unread:$conversationId');
  }

  @override
  Future<void> toggleConversationPin(String conversationId) async {
    actions.add('conversation-pin:$conversationId');
  }

  @override
  Future<void> toggleConversationFollowed(String conversationId) async {
    actions.add('conversation-followed:$conversationId');
  }

  @override
  Future<void> toggleConversationHidden(String conversationId) async {
    actions.add('conversation-hidden:$conversationId');
  }

  @override
  Future<void> deleteConversation(String conversationId) async {
    actions.add('conversation-delete:$conversationId');
  }

  @override
  Future<AiGroupConversation?> markAiGroupUnread(String groupId) async {
    actions.add('group-unread:$groupId');
    return super.markAiGroupUnread(groupId);
  }

  @override
  Future<AiGroupConversation?> toggleAiGroupPin(String groupId) async {
    actions.add('group-pin:$groupId');
    return super.toggleAiGroupPin(groupId);
  }

  @override
  Future<AiGroupConversation?> toggleAiGroupFollowed(String groupId) async {
    actions.add('group-followed:$groupId');
    return super.toggleAiGroupFollowed(groupId);
  }

  @override
  Future<AiGroupConversation?> toggleAiGroupHidden(String groupId) async {
    actions.add('group-hidden:$groupId');
    return super.toggleAiGroupHidden(groupId);
  }

  @override
  Future<void> deleteAiGroup(String groupId) async {
    actions.add('group-delete:$groupId');
  }
}

class _FakeCircleRepository extends MobileRepository {
  _FakeCircleRepository({
    this.failEmployees = false,
    this.failLike = false,
  });

  final bool failEmployees;
  final bool failLike;

  @override
  Future<MobileMeData> loadMe() async {
    return MobileMeData.adminFallback();
  }

  @override
  Future<List<AiEmployeeProfile>> loadAiEmployees() async {
    if (failEmployees) throw const MobileRepositoryException('offline');
    return adminDutyEmployeeProfiles();
  }

  @override
  Future<List<AiCirclePost>> loadAiCirclePosts() async {
    return const [
      AiCirclePost(
        id: 1,
        authorKind: 'employee',
        authorUserId: null,
        employeeId: 'site-content-editor',
        authorName: '静态站内容编辑员',
        authorAvatar: null,
        body: '已完成首页内容巡检。',
        sourceType: 'work_report',
        createdAt: '2026-06-30T04:12:00',
        likeCount: 0,
        likedByMe: false,
        comments: [
          AiCircleComment(
            id: 10,
            authorName: 'admin',
            body: '收到',
            createdAt: '2026-06-30T04:13:00',
          ),
        ],
      ),
    ];
  }

  @override
  Future<void> toggleAiCircleLike(int postId) async {
    if (failLike) {
      throw const MobileRepositoryException('failed to connect to desktop');
    }
  }
}

class _FakeNotificationRepository extends MobileRepository {
  @override
  Future<List<PendingNotification>> loadPendingNotifications() async {
    return const [
      PendingNotification(
        id: 88,
        title: '移动端通知',
        body: '后台任务已经完成',
        route: '',
        channel: 'system',
      ),
    ];
  }
}

class _FakeAuthRepository extends MobileRepository {
  _FakeAuthRepository(MobileApiClient client) : super(client: client);

  final List<Map<String, Object?>> logins = [];

  @override
  Future<void> login({
    required String username,
    required String password,
    required bool adminMode,
    bool rememberPass = false,
    bool autoLogin = false,
  }) async {
    logins.add({
      'username': username.trim(),
      'password': password,
      'adminMode': adminMode,
      'rememberPass': rememberPass,
      'autoLogin': autoLogin,
    });
    await client.saveLoginPreferences(
      username: username,
      password: password,
      rememberPassword: rememberPass,
      autoLogin: autoLogin,
    );
  }
}

class _FakeLegalApi extends MobileApiClient {
  final List<String> acceptedVersions = [];

  @override
  Future<void> saveLegalAcceptedVersion(String version) async {
    acceptedVersions.add(version.trim());
  }
}

class _FakeSettingsApi extends MobileApiClient {
  _FakeSettingsApi({this.session = MobileSessionData.empty});

  final List<String> feedbackMessages = [];
  final List<Map<String, Object?>> updateChecks = [];
  final List<Map<String, Object?>> settingSaves = [];
  MobileSessionData session;
  MobileUpdateCheckResult updateResult = const MobileUpdateCheckResult(
    available: false,
    force: false,
    versionName: MobileAndroidBuild.versionName,
    downloadUrl: '',
    raw: {'ok': true},
  );

  @override
  Future<MobileSessionData> loadSession() async => session;

  @override
  Future<void> saveLocalSettings({
    String? themeMode,
    bool? biometricEnabled,
  }) async {
    settingSaves.add({
      if (themeMode != null) 'themeMode': themeMode,
      if (biometricEnabled != null) 'biometricEnabled': biometricEnabled,
    });
    if (themeMode != null) {
      session = session.copyWith(themeMode: themeMode);
    }
    if (biometricEnabled != null) {
      session = session.copyWith(biometricEnabled: biometricEnabled);
    }
  }

  @override
  Future<MobileEnvelope<Map<String, Object?>>> submitFeedback(
    String message, {
    String contact = '',
  }) async {
    feedbackMessages.add(message.trim());
    return const MobileEnvelope<Map<String, Object?>>(
      success: true,
      message: '',
      data: null,
      raw: {'ok': true},
    );
  }

  @override
  Future<MobileUpdateCheckResult> checkForUpdate({
    int currentVersionCode = MobileAndroidBuild.versionCode,
    String sku = MobileAndroidBuild.productSku,
  }) async {
    updateChecks.add({
      'currentVersionCode': currentVersionCode,
      'sku': sku,
    });
    return updateResult;
  }
}

class _FakeUpdateInstaller implements AndroidPackageUpdateInstaller {
  _FakeUpdateInstaller({this.message = ''});

  final String message;
  final List<MobileUpdateCheckResult> calls = [];

  @override
  Future<String> startPackageUpdate(MobileUpdateCheckResult result) async {
    calls.add(result);
    return message;
  }
}

class _FakeProfileApi extends MobileApiClient {
  _FakeProfileApi({
    this.deleteError = '',
    this.profilePage = const MobileProfilePageConfig.disabled(),
    this.session = MobileSessionData.empty,
  });

  final String deleteError;
  final MobileProfilePageConfig profilePage;
  final List<String> deletePasswords = [];
  final List<Map<String, String>> localProfileSaves = [];
  MobileSessionData session;
  var exportCalls = 0;
  var walletLoads = 0;
  var appConfigLoads = 0;
  var meLoads = 0;

  @override
  Future<MobileSessionData> loadSession() async => session;

  @override
  Future<void> clearActiveAuth() async {
    session = session.copyWith(
      accessToken: '',
      refreshToken: '',
      sessionId: '',
      username: '',
      accountKind: '',
      userId: 0,
      marketAccessToken: '',
      marketRefreshToken: '',
      relayDesktopId: '',
      relayBaseUrl: '',
      localBaseUrl: '',
      relaySessionToken: '',
      relayAccountId: '',
      relayTenantId: '',
      relayPairedAt: '',
      setupComplete: false,
      autoLogin: false,
      walletBalanceJson: '',
      inflightRelayTasks: const <String, String>{},
      cachedChatMessages: const <String, List<Map<String, Object?>>>{},
    );
  }

  @override
  Future<void> saveLocalProfile({
    required String displayName,
    required String avatarSource,
  }) async {
    localProfileSaves.add({
      'displayName': displayName.trim(),
      'avatarSource': avatarSource.trim(),
    });
    session = session.copyWith(
      username:
          displayName.trim().isEmpty ? session.username : displayName.trim(),
      localAvatarSource: avatarSource.trim(),
    );
  }

  @override
  Future<void> saveWalletBalanceJson(String json) async {
    session = session.copyWith(walletBalanceJson: json.trim());
  }

  @override
  Future<MobileEnvelope<WalletBalanceData>> walletBalance() async {
    walletLoads += 1;
    return MobileEnvelope<WalletBalanceData>(
      success: true,
      message: '',
      data: WalletBalanceData.androidCurrentFallback(),
      raw: const {'ok': true},
    );
  }

  @override
  Future<MobileAppConfigData> appConfig({
    int currentVersionCode = MobileAndroidBuild.versionCode,
    String sku = MobileAndroidBuild.productSku,
  }) async {
    appConfigLoads += 1;
    return MobileAppConfigData(
      ok: true,
      legalVersion: '1',
      profilePage: profilePage,
      raw: const {'ok': true},
    );
  }

  @override
  Future<MobileEnvelope<Map<String, Object?>>> me() async {
    meLoads += 1;
    return const MobileEnvelope<Map<String, Object?>>(
      success: true,
      message: '',
      data: {
        'user': {
          'username': 'admin',
          'display_name': 'admin',
          'avatar_url': '',
        },
        'account_kind': 'admin',
      },
      raw: {'ok': true},
    );
  }

  @override
  Future<MobileEnvelope<Map<String, Object?>>> exportAccountData() async {
    exportCalls += 1;
    return const MobileEnvelope<Map<String, Object?>>(
      success: true,
      message: '',
      data: null,
      raw: {'ok': true},
    );
  }

  @override
  Future<MobileEnvelope<Map<String, Object?>>> deleteAccount(
    String password,
  ) async {
    deletePasswords.add(password);
    if (deleteError.isNotEmpty) {
      throw MobileApiException(
        statusCode: 500,
        message: deleteError,
        body: const {'success': false},
      );
    }
    await clearActiveAuth();
    return const MobileEnvelope<Map<String, Object?>>(
      success: true,
      message: '',
      data: null,
      raw: {'ok': true},
    );
  }
}

class _SlowWalletProfileApi extends _FakeProfileApi {
  _SlowWalletProfileApi({required super.session});

  final remoteWallet = Completer<WalletBalanceData>();

  @override
  Future<MobileEnvelope<WalletBalanceData>> walletBalance() async {
    walletLoads += 1;
    final wallet = await remoteWallet.future;
    return MobileEnvelope<WalletBalanceData>(
      success: true,
      message: '',
      data: wallet,
      raw: const {'ok': true},
    );
  }
}
