import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:skeletonizer/skeletonizer.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_api.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_models.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_session_store.dart';
import 'package:xcagi_flutter_poc/src/data/mobile_repository.dart';
import 'package:xcagi_flutter_poc/src/data/ai_employee_profile.dart';
import 'package:xcagi_flutter_poc/src/features/chat/chat_screen.dart';
import 'package:xcagi_flutter_poc/src/features/circle/ai_circle_screen.dart';
import 'package:xcagi_flutter_poc/src/features/discover/discover_screen.dart';
import 'package:xcagi_flutter_poc/src/features/approval/native_approval_workspace.dart';
import 'package:xcagi_flutter_poc/src/features/tasks/task_list_screen.dart';
import 'package:xcagi_flutter_poc/src/features/webview/desktop_tool_webview_screen.dart';
import 'package:xcagi_flutter_poc/src/models/conversation.dart';

MobileNavMenuItem _nav(String key, String name, String group,
        {bool desktop = false, String? path}) =>
    MobileNavMenuItem(
        key: key,
        name: name,
        icon: '',
        path: path ?? '/$key',
        source: 'core',
        modId: null,
        mobileGroup: group,
        requiresDesktop: desktop);

Future<void> _show(
  WidgetTester tester,
  _Repository repository, {
  bool reduceMotion = false,
  double textScale = 1,
  Size size = const Size(430, 1400),
}) async {
  tester.view.devicePixelRatio = 1;
  tester.view.physicalSize = size;
  addTearDown(tester.view.resetDevicePixelRatio);
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(() async {
    await repository.dispose();
    repository.client.dispose();
  });
  await tester.pumpWidget(MaterialApp(
      builder: (context, child) => MediaQuery(
            data: MediaQuery.of(context).copyWith(
                disableAnimations: reduceMotion,
                textScaler: TextScaler.linear(textScale)),
            child: child!,
          ),
      home: Scaffold(body: DiscoverScreen(repository: repository))));
  await tester.pump();
}

void main() {
  testWidgets(
      'pending menu retains useful task and data entries without fake device status',
      (tester) async {
    final repository = _Repository()
      ..pendingNav = Completer<List<MobileNavMenuItem>>()
      ..pendingDevices = Completer<List<MobileDesktopDevice>>();
    await _show(tester, repository);
    for (final title in [
      '工作台',
      'AI交流',
      'AI交流圈',
      '待办与任务',
      '业务应用',
      '资料与数据',
      '我的电脑',
      '任务',
      '审批',
      '拍照与文件'
    ]) {
      expect(find.text(title), findsOneWidget);
    }
    expect(find.text('正在读取电脑状态…'), findsOneWidget);
    expect(find.byKey(const ValueKey('workbench-devices-skeleton')),
        findsOneWidget);
    expect(find.text('尚未绑定电脑'), findsNothing);
    expect(find.text('员工工作台'), findsNothing);
    expect(find.text('数据对接中心'), findsNothing);
    expect(find.text('通知与公告'), findsNothing);
    expect(find.text('扫码绑定电脑'), findsOneWidget);
  });

  testWidgets(
      'loading skeletons respect reduced motion and vanish on empty results',
      (tester) async {
    final repository = _Repository()
      ..pendingNav = Completer<List<MobileNavMenuItem>>()
      ..pendingDevices = Completer<List<MobileDesktopDevice>>();
    await _show(tester, repository, reduceMotion: true);
    final skeletons = tester.widgetList<Skeletonizer>(
        find.byWidgetPredicate((widget) => widget is Skeletonizer));
    expect(skeletons, hasLength(2));
    for (final skeleton in skeletons) {
      expect(skeleton.effect, isA<SolidColorEffect>());
      expect(skeleton.enableSwitchAnimation, isFalse);
      expect(skeleton.ignorePointers, isTrue);
    }
    expect(find.text('在线'), findsNothing);
    expect(find.text('离线'), findsNothing);
    await tester.pumpAndSettle();
    repository.pendingNav!.complete([]);
    repository.pendingDevices!.complete([]);
    await tester.pumpAndSettle();
    expect(find.byWidgetPredicate((widget) => widget is Skeletonizer),
        findsNothing);
    expect(find.text('暂无可用业务应用'), findsOneWidget);
    expect(find.text('尚未绑定电脑'), findsOneWidget);
  });

  testWidgets('failed requests show errors without loading skeletons',
      (tester) async {
    await _show(
        tester,
        _Repository()
          ..navError = true
          ..deviceError = true);
    expect(find.text('应用加载失败'), findsOneWidget);
    expect(find.text('无法确认电脑状态'), findsOneWidget);
    expect(find.byWidgetPredicate((widget) => widget is Skeletonizer),
        findsNothing);
    expect(find.text('在线'), findsNothing);
  });

  testWidgets(
      'device identity and status fit large text without inventing actions',
      (tester) async {
    final repository = _Repository()
      ..devices = [
        const MobileDesktopDevice(
          deviceId: 'office',
          label: '办公室用于处理业务的共享电脑',
          platform: 'Windows',
          online: false,
          lastSeenAt: '',
        )
      ];
    await _show(tester, repository,
        reduceMotion: true, textScale: 1.6, size: const Size(320, 2200));
    final card = find.byKey(const ValueKey('workbench-device-office'));
    expect(card, findsOneWidget);
    expect(find.text('办公室用于处理业务的共享电脑'), findsOneWidget);
    expect(find.text('离线'), findsOneWidget);
    expect(find.text('最近在线：暂无记录'), findsOneWidget);
    expect(find.descendant(of: card, matching: find.byType(InkWell)),
        findsNothing);
    expect(tester.takeException(), isNull);
  });

  testWidgets(
      'shared groups deduplicate entries and AI ecosystem opens its actual web page',
      (tester) async {
    final repository = _Repository()
      ..menu = [
        _nav('approval-hub', '审批中心', 'tasks'),
        _nav('business-docking', '数据对接中心', 'data'),
        _nav('ai-ecosystem', 'AI生态', 'business'),
        _nav('settings', '设置', 'business'),
        _nav('admin-entitlements', '授权管理', 'business'),
      ];
    await _show(tester, repository);
    expect(
        find.byKey(const ValueKey('workbench-approval-hub')), findsOneWidget);
    expect(find.text('数据对接中心'), findsOneWidget);
    expect(find.text('设置'), findsNothing);
    expect(find.text('授权管理'), findsNothing);
    await tester.tap(find.text('AI生态'));
    await tester.pumpAndSettle();
    final web = tester.widget<DesktopToolWebViewScreen>(
        find.byType(DesktopToolWebViewScreen));
    expect(web.path, '/ai-ecosystem');
    expect(web.api, same(repository.client));
  });

  testWidgets(
      'empty authorized menu never exposes desktop application fallbacks',
      (tester) async {
    await _show(tester, _Repository());
    expect(
        find.byKey(const ValueKey('workbench-business-docking')), findsNothing);
    expect(find.byKey(const ValueKey('workbench-employee-workflow')),
        findsNothing);
    expect(
        find.byKey(const ValueKey('workbench-approval-hub')), findsOneWidget);
  });
  for (final key in ['business-docking', 'ai-ecosystem', 'approval-hub']) {
    testWidgets('authorized $key preserves its Mod scoped route',
        (tester) async {
      final path = '/mod/authorized/$key?view=mobile';
      final repository = _Repository()
        ..menu = [_nav(key, '授权应用', 'business', path: path)];
      await _show(tester, repository);
      await tester.tap(find.byKey(ValueKey('workbench-$key')));
      await tester.pumpAndSettle();
      if (key == 'approval-hub') {
        final native = tester.widget<NativeApprovalWorkspace>(
            find.byType(NativeApprovalWorkspace));
        expect(native.apiBase, 'api/mod/authorized');
        expect(native.repository, same(repository));
        expect(find.byType(DesktopToolWebViewScreen), findsNothing);
      } else {
        final web = tester.widget<DesktopToolWebViewScreen>(
            find.byType(DesktopToolWebViewScreen));
        expect(web.path, path);
        expect(web.api, same(repository.client));
      }
    });
  }

  for (final change in ['account', 'backend']) {
    testWidgets(
        'first $change change clears completed data after cached session load',
        (tester) async {
      final api = MobileApiClient(
          sessionStore: MemoryMobileSessionStore(const MobileSessionData(
        accessToken: 'account-a',
        userId: 1,
        serverMode: 'lan',
        fhdHost: '10.0.0.9:5011',
        localBaseUrl: 'http://10.0.0.9:5011/',
      )));
      await api.loadSession();
      final repository = _Repository(api: api)
        ..menu = [_nav('old-app', '原账号应用', 'business')]
        ..devices = [
          const MobileDesktopDevice(
              deviceId: 'old-device',
              label: '原账号电脑',
              platform: 'Windows',
              online: true,
              lastSeenAt: '')
        ];
      await _show(tester, repository);
      expect(find.text('原账号应用'), findsOneWidget);
      expect(find.text('原账号电脑'), findsOneWidget);
      repository.pendingNav = Completer<List<MobileNavMenuItem>>();
      repository.pendingDevices = Completer<List<MobileDesktopDevice>>();
      if (change == 'account') {
        await api.clearActiveAuth();
      } else {
        await api.saveLocalSettings(serverMode: 'cloud');
      }
      await tester.pump();
      expect(find.text('原账号应用'), findsNothing);
      expect(find.text('原账号电脑'), findsNothing);
      expect(find.text('正在读取电脑状态…'), findsOneWidget);
      repository.pendingNav!.complete([_nav('new-app', '当前应用', 'business')]);
      repository.pendingDevices!.complete([]);
      await tester.pumpAndSettle();
      expect(find.text('当前应用'), findsOneWidget);
      expect(find.text('尚未绑定电脑'), findsOneWidget);
    });
  }

  testWidgets(
      'device errors retry into actual status and only required actions show computer hint',
      (tester) async {
    final repository = _Repository()
      ..deviceError = true
      ..menu = [
        _nav('print', '打印管理', 'business'),
        _nav('desktop-job', '电脑任务', 'computer', desktop: true),
      ];
    await _show(tester, repository);
    expect(find.text('无法确认电脑状态'), findsOneWidget);
    expect(find.text('离线'), findsNothing);
    expect(find.text('需要电脑执行 · 电脑状态待确认'), findsOneWidget);
    repository.deviceError = false;
    repository.devices = [
      const MobileDesktopDevice(
          deviceId: 'paired-a',
          label: '办公室电脑',
          platform: 'Windows',
          online: true,
          lastSeenAt: '2026-11-17T08:30:00Z')
    ];
    await tester.tap(find.widgetWithText(TextButton, '重试'));
    await tester.pumpAndSettle();
    expect(find.text('办公室电脑'), findsOneWidget);
    expect(find.text('在线'), findsOneWidget);
    expect(find.textContaining('最近在线：2026-11-17'), findsOneWidget);
    expect(find.text('需要电脑执行 · 有电脑在线'), findsOneWidget);
    expect(find.text('扫码绑定电脑'), findsOneWidget);
    expect(repository.deviceCalls, 2);
  });

  testWidgets(
      'tasks and AI circle keep native navigation with the selected repository',
      (tester) async {
    final repository = _Repository();
    await _show(tester, repository);
    await tester.tap(find.byKey(const ValueKey('workbench-tasks')));
    await tester.pumpAndSettle();
    expect(
        tester.widget<TaskListScreen>(find.byType(TaskListScreen)).repository,
        same(repository));
    Navigator.of(tester.element(find.byType(TaskListScreen))).pop();
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('workbench-ai-circle')));
    await tester.pumpAndSettle();
    expect(
        tester.widget<AiCircleScreen>(find.byType(AiCircleScreen)).repository,
        same(repository));
  });

  testWidgets('photo and file entry opens native assistant attachments',
      (tester) async {
    final repository = _Repository();
    await _show(tester, repository);
    await tester.tap(find.byKey(const ValueKey('workbench-photo-files')));
    await tester.pumpAndSettle();
    final chat = tester.widget<ChatScreen>(find.byType(ChatScreen));
    expect(chat.repository, same(repository));
    expect(chat.conversation.type, ConversationType.pinnedAssistant);
  });
}

class _Repository extends MobileRepository {
  _Repository({MobileApiClient? api})
      : super(
            client: api ??
                MobileApiClient(sessionStore: MemoryMobileSessionStore()));
  List<MobileNavMenuItem> menu = [];
  List<MobileDesktopDevice> devices = [];
  Completer<List<MobileNavMenuItem>>? pendingNav;
  Completer<List<MobileDesktopDevice>>? pendingDevices;
  bool deviceError = false;
  bool navError = false;
  int deviceCalls = 0;
  @override
  Future<List<MobileNavMenuItem>> loadNavMenu() async {
    if (navError) throw StateError('offline');
    return pendingNav == null ? menu : await pendingNav!.future;
  }

  @override
  Future<List<MobileDesktopDevice>> loadDesktopDevices() async {
    deviceCalls++;
    if (deviceError) throw StateError('offline');
    return pendingDevices == null ? devices : await pendingDevices!.future;
  }

  @override
  Future<List<MobileTaskSummary>> loadTasks({int limit = 50}) async => [];
  @override
  Future<List<ChatMessage>> loadInitialMessages(
          ConversationItem conversation) async =>
      [];
  @override
  Future<MobileMeData> loadMe() async => MobileMeData.adminFallback();
  @override
  Future<List<AiEmployeeProfile>> loadAiEmployees() async => [];
  @override
  Future<List<AiCirclePost>> loadAiCirclePosts() async => [];
}
