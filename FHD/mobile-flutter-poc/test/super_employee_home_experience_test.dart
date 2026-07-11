import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_api.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_models.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_session_store.dart';
import 'package:xcagi_flutter_poc/src/data/ai_employee_profile.dart';
import 'package:xcagi_flutter_poc/src/data/assistant_assets.dart';
import 'package:xcagi_flutter_poc/src/data/mobile_repository.dart';
import 'package:xcagi_flutter_poc/src/features/messages/message_list_screen.dart';
import 'package:xcagi_flutter_poc/src/models/conversation.dart';
import 'package:xcagi_flutter_poc/src/policy/pinned_ids.dart';
import 'package:xcagi_flutter_poc/src/theme/app_theme.dart';
import 'package:xcagi_flutter_poc/src/widgets/super_employee_run_capsule.dart';

void main() {
  testWidgets('run capsule never presents unavailable states as idle',
      (tester) async {
    const cases = {
      SuperEmployeeRunAvailability.checking: '正在检查执行电脑',
      SuperEmployeeRunAvailability.offline: '执行电脑离线',
      SuperEmployeeRunAvailability.unpaired: '尚未配对执行电脑',
      SuperEmployeeRunAvailability.unknown: '执行状态未知',
    };

    for (final entry in cases.entries) {
      await tester.pumpWidget(
        MaterialApp(
          theme: AppTheme.light(),
          home: Scaffold(
            body: SuperEmployeeRunCapsule(
              runs: const [],
              availability: entry.key,
              onTap: () {},
            ),
          ),
        ),
      );

      expect(find.text(entry.value), findsOneWidget);
      expect(find.text('待命'), findsNothing);
    }
  });

  testWidgets('successful empty status request is the only idle state',
      (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: Scaffold(
          body: SuperEmployeeRunCapsule(
            runs: const [],
            availability: SuperEmployeeRunAvailability.ready,
            onTap: () {},
          ),
        ),
      ),
    );

    expect(find.text('待命'), findsNWidgets(4));
  });

  testWidgets('message home reports unpaired executor without calling runs API',
      (tester) async {
    final repository = _RunStatusRepository(
      session: MobileSessionData.empty,
      error: StateError('must not load'),
    );

    await _pumpMessageHome(tester, repository);

    expect(find.text('尚未配对执行电脑'), findsOneWidget);
    expect(find.text('待命'), findsNothing);
    expect(repository.runLoads, 0);
  });

  testWidgets('message home distinguishes offline and unknown run states',
      (tester) async {
    final offline = _RunStatusRepository(
      session: _pairedSession,
      error: Exception('SocketException: Connection refused'),
    );
    await _pumpMessageHome(tester, offline);
    expect(find.text('执行电脑离线'), findsOneWidget);
    expect(find.text('待命'), findsNothing);

    final unknown = _RunStatusRepository(
      session: _pairedSession,
      error: Exception('服务端返回 500'),
    );
    await _pumpMessageHome(tester, unknown);
    expect(find.text('执行状态未知'), findsOneWidget);
    expect(find.text('待命'), findsNothing);

    final expiredPairing = _RunStatusRepository(
      session: _pairedSession,
      error: Exception('401 unauthorized'),
    );
    await _pumpMessageHome(tester, expiredPairing);
    expect(find.text('尚未配对执行电脑'), findsOneWidget);
    expect(find.text('待命'), findsNothing);
  });

  testWidgets('returning from chat refreshes the latest conversation preview',
      (tester) async {
    tester.view.devicePixelRatio = 1;
    tester.view.physicalSize = const Size(430, 900);
    addTearDown(tester.view.resetDevicePixelRatio);
    addTearDown(tester.view.resetPhysicalSize);
    final repository = _ConversationRefreshRepository();
    var preview = '进入聊天前的摘要';
    var refreshes = 0;

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: StatefulBuilder(
          builder: (context, setState) => Scaffold(
            body: MessageListScreen(
              repository: repository,
              items: [
                ConversationItem(
                  id: PinnedIds.assistant,
                  type: ConversationType.pinnedAssistant,
                  title: '小C助理',
                  subtitle: preview,
                  timestampText: '刚刚',
                  isPinned: true,
                ),
              ],
              onRefresh: () async {
                refreshes += 1;
                setState(() => preview = '返回首页后的最新回复');
              },
            ),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    await tester.tap(find.text('小C助理'));
    await tester.pumpAndSettle();
    expect(find.text('问问小C…'), findsOneWidget);

    await tester.tap(find.byTooltip('返回'));
    await tester.pumpAndSettle();

    expect(refreshes, 1);
    expect(find.text('返回首页后的最新回复'), findsOneWidget);
  });
}

const _pairedSession = MobileSessionData(
  serverMode: 'lan',
  localAccessToken: 'desktop-jwt',
  localBaseUrl: 'http://192.168.10.2:17500/fhd-api',
);

Future<void> _pumpMessageHome(
  WidgetTester tester,
  MobileRepository repository,
) async {
  await tester.pumpWidget(
    MaterialApp(
      theme: AppTheme.light(),
      home: Scaffold(
        body: MessageListScreen(repository: repository, items: const []),
      ),
    ),
  );
  await tester.pumpAndSettle();
}

class _RunStatusRepository extends MobileRepository {
  _RunStatusRepository(
      {required MobileSessionData session, required this.error})
      : super(
          client: MobileApiClient(
            sessionStore: MemoryMobileSessionStore(session),
          ),
        );

  final Object error;
  int runLoads = 0;

  @override
  Future<List<RelayRunSummary>> loadRelayRuns({
    String threadId = '',
    bool activeOnly = false,
    int limit = 100,
    void Function()? onCloudSyncFailed,
  }) async {
    runLoads += 1;
    throw error;
  }
}

class _ConversationRefreshRepository extends MobileRepository {
  _ConversationRefreshRepository()
      : super(
          client: MobileApiClient(
            sessionStore: MemoryMobileSessionStore(_pairedSession),
          ),
        );

  @override
  Future<List<RelayRunSummary>> loadRelayRuns({
    String threadId = '',
    bool activeOnly = false,
    int limit = 100,
    void Function()? onCloudSyncFailed,
  }) async =>
      const [];

  @override
  Future<List<ChatMessage>> loadInitialMessages(
    ConversationItem conversation,
  ) async =>
      const [];

  @override
  Future<MobileMeData> loadMe() async => MobileMeData.adminFallback();

  @override
  Future<List<AiEmployeeProfile>> loadAiEmployees() async => const [];

  @override
  Future<AssistantEmployeeAvailability>
      loadAssistantEmployeeAvailability() async {
    return const AssistantEmployeeAvailability(
      onlineConversationIds: {PinnedIds.codex},
    );
  }
}
