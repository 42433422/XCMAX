import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_api.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_models.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_session_store.dart';
import 'package:xcagi_flutter_poc/src/data/ai_employee_profile.dart';
import 'package:xcagi_flutter_poc/src/data/mobile_repository.dart';
import 'package:xcagi_flutter_poc/src/features/chat/chat_screen.dart';
import 'package:xcagi_flutter_poc/src/features/devtools/execution_review_screen.dart';
import 'package:xcagi_flutter_poc/src/models/conversation.dart';
import 'package:xcagi_flutter_poc/src/policy/pinned_ids.dart';
import 'package:xcagi_flutter_poc/src/theme/app_theme.dart';

void main() {
  test('LAN conversations keep multi-round context and archive independently',
      () async {
    final store = MemoryMobileSessionStore(_lanSession);
    final api = _LanTaskApi(store);
    final repository = MobileRepository(client: api);

    final first =
        await repository.startNewSuperEmployeeConversation(_codexConversation);
    await repository.streamMessage(
      conversation: _codexConversation,
      body: '第一轮：检查发送按钮',
    );
    await repository.streamMessage(
      conversation: _codexConversation,
      body: '第二轮：继续修复',
    );
    final second =
        await repository.startNewSuperEmployeeConversation(_codexConversation);
    await repository.streamMessage(
      conversation: _codexConversation,
      body: '另一个对话：检查局域网',
    );

    expect(first.threadId, startsWith('local-'));
    expect(second.threadId, startsWith('local-'));
    expect(second.threadId, isNot(first.threadId));
    expect(api.streamContexts, hasLength(3));
    expect(api.streamContexts[0]['thread_id'], first.threadId);
    expect(api.streamContexts[1]['thread_id'], first.threadId);
    expect(api.streamContexts[2]['thread_id'], second.threadId);
    expect(
      api.streamContexts.map((item) => item['client_task_id']).toSet(),
      hasLength(3),
    );

    final threads =
        await repository.loadSuperEmployeeThreads(_codexConversation);
    expect(threads, hasLength(2));
    expect(threads.every((thread) => thread.sourceLabel == '局域网'), isTrue);

    await repository.switchSuperEmployeeThread(
      _codexConversation.id,
      first.threadId,
    );
    final firstTranscript = await repository.loadActiveSuperEmployeeMessages(
      _codexConversation.id,
    );
    expect(firstTranscript, hasLength(4));
    expect(firstTranscript[0].body, '第一轮：检查发送按钮');
    expect(firstTranscript[2].body, '第二轮：继续修复');

    await repository.archiveSuperEmployeeThread(
      _codexConversation.id,
      first.threadId,
    );
    expect(api.relayArchiveCalls, 0);
    expect(
      await repository.activeSuperEmployeeThreadId(_codexConversation.id),
      isEmpty,
    );
    final visible =
        await repository.loadSuperEmployeeThreads(_codexConversation);
    expect(visible.map((thread) => thread.threadId), [second.threadId]);
    final withArchive = await repository.loadSuperEmployeeThreads(
      _codexConversation,
      includeArchived: true,
    );
    expect(
      withArchive
          .singleWhere((thread) => thread.threadId == first.threadId)
          .archived,
      isTrue,
    );

    // A new repository instance represents an app process restart. The second
    // LAN conversation and its transcript must still be switchable.
    final restarted = MobileRepository(client: _LanTaskApi(store));
    await restarted.switchSuperEmployeeThread(
      _codexConversation.id,
      second.threadId,
    );
    final restored = await restarted.loadActiveSuperEmployeeMessages(
      _codexConversation.id,
    );
    expect(restored, hasLength(2));
    expect(restored.first.body, '另一个对话：检查局域网');
  });

  test('LAN runs share execution review with cloud and survive restart',
      () async {
    final store = MemoryMobileSessionStore(_lanSession);
    final api = _LanTaskApi(store, includeCloudRun: true);
    final repository = MobileRepository(client: api);

    await repository.streamMessage(
      conversation: _codexConversation,
      body: '完成一个本地任务',
    );

    final restarted = MobileRepository(client: api);
    final runs = await restarted.loadRelayRuns();
    expect(runs, hasLength(2));
    expect(runs.map((run) => run.sourceLabel).toSet(), {'局域网', '云中继'});
    final local = runs.singleWhere((run) => run.source == 'lan');
    expect(local.taskId, startsWith('local-run-'));
    expect(local.status, 'completed');
    expect(local.message, '完成一个本地任务');
    expect(local.resultText, contains('局域网回复'));
  });

  test('cloud run failure keeps local history and reports partial sync',
      () async {
    final store = MemoryMobileSessionStore(_lanSession);
    final api = _LanTaskApi(store, cloudHistoryFailure: true);
    final repository = MobileRepository(client: api);

    await repository.streamMessage(
      conversation: _codexConversation,
      body: '保留的本地执行记录',
    );
    var cloudSyncFailed = false;

    final runs = await repository.loadRelayRuns(
      onCloudSyncFailed: () => cloudSyncFailed = true,
    );

    expect(runs, hasLength(1));
    expect(runs.single.source, 'lan');
    expect(runs.single.message, '保留的本地执行记录');
    expect(cloudSyncFailed, isTrue);
  });

  test('provider usage failure is recorded once without direct or cloud retry',
      () async {
    final store = MemoryMobileSessionStore(_lanSession);
    final api = _LanTaskApi(store, semanticStreamError: true);
    final repository = MobileRepository(client: api);

    await expectLater(
      repository.streamMessage(
        conversation: _codexConversation,
        body: '触发真实额度错误',
      ),
      throwsA(
        isA<MobileRepositoryException>().having(
          (error) => error.message,
          'message',
          contains('用量已耗尽'),
        ),
      ),
    );

    expect(api.streamCalls, 1);
    expect(api.directCalls, 0);
    expect(api.relayCancelCalls, 0);
    final run = (await repository.loadRelayRuns()).single;
    expect(run.status, 'failed');
    expect(run.resultText, contains('用量已耗尽'));
  });

  test('restart reconciles an unfinished LAN run without claiming completion',
      () async {
    const taskId = 'local-run-before-restart';
    final store = MemoryMobileSessionStore(
      const MobileSessionData(
        serverMode: 'lan',
        localAccessToken: 'desktop-jwt',
        localBaseUrl: 'http://192.168.10.2:17500/fhd-api',
        localSuperEmployeeRuns: {
          taskId: {
            'task_id': taskId,
            'thread_id': 'local-thread-before-restart',
            'conversation_id': PinnedIds.codex,
            'employee_id': 'codex-super-employee',
            'kind': 'codex.invoke',
            'status': 'running',
            'attempt_no': 1,
            'created_at': '2026-07-10T00:00:00Z',
            'updated_at': '2026-07-10T00:00:00Z',
            'source': 'lan',
            'payload': {'message': '重启前任务'},
          },
        },
      ),
    );
    final repository = MobileRepository(client: _LanTaskApi(store));

    final run = (await repository.loadRelayRuns()).single;

    expect(run.status, 'blocked');
    expect(run.sourceLabel, '局域网');
    expect(run.resultText, contains('应用重启前未获得'));
    expect(
      (await store.load()).localSuperEmployeeRuns[taskId]?['status'],
      'blocked',
    );
  });

  test('LAN cancel is cancelled only after authenticated server ack', () async {
    final store = MemoryMobileSessionStore(_lanSession);
    final api = _LanTaskApi(store, blockStreamUntilCancelled: true);
    final repository = MobileRepository(client: api);
    RelayTaskProgress? progress;

    final invocation = repository.streamMessage(
      conversation: _codexConversation,
      body: '长任务等待真实取消',
      onStatus: (value) => progress = value,
    );
    final expectation = expectLater(invocation, throwsA(anything));
    await api.streamStarted.future;

    expect(progress?.sourceLabel, '局域网');
    final acknowledged = await repository.cancelRelayTask(progress!.taskId);
    expect(acknowledged, isTrue);
    await expectation;

    expect(api.localCancelCalls, 1);
    expect(api.lastCancelPath, contains(progress!.taskId));
    expect(api.relayCancelCalls, 0);
    final run = (await repository.loadRelayRuns())
        .singleWhere((item) => item.taskId == progress!.taskId);
    expect(run.status, 'cancelled');
    expect(run.resultText, contains('电脑已确认停止'));
  });

  test('LAN disconnect without server ack never pretends CLI was cancelled',
      () async {
    final store = MemoryMobileSessionStore(_lanSession);
    final api = _LanTaskApi(
      store,
      blockStreamUntilCancelled: true,
      cancelAck: false,
    );
    final repository = MobileRepository(client: api);
    RelayTaskProgress? progress;

    final invocation = repository.streamMessage(
      conversation: _codexConversation,
      body: '取消接口不可用',
      onStatus: (value) => progress = value,
    );
    final expectation = expectLater(invocation, throwsA(anything));
    await api.streamStarted.future;

    final acknowledged = await repository.cancelRelayTask(progress!.taskId);
    expect(acknowledged, isFalse);
    await expectation;

    final run = (await repository.loadRelayRuns())
        .singleWhere((item) => item.taskId == progress!.taskId);
    expect(run.status, isNot('cancelled'));
    expect(run.status, 'blocked');
    expect(run.resultText, '只能停止等待，电脑任务可能继续');
    expect(api.relayCancelCalls, 0);
  });

  test('session JSON preserves local threads and runs', () {
    const session = MobileSessionData(
      localSuperEmployeeThreads: {
        'local-thread': {
          'thread_id': 'local-thread',
          'source': 'lan',
        },
      },
      localSuperEmployeeRuns: {
        'local-run': {
          'task_id': 'local-run',
          'status': 'completed',
          'source': 'lan',
        },
      },
    );

    final restored = MobileSessionData.fromJson(session.toJson());

    expect(
      restored.localSuperEmployeeThreads['local-thread']?['source'],
      'lan',
    );
    expect(
      restored.localSuperEmployeeRuns['local-run']?['status'],
      'completed',
    );
  });

  testWidgets('execution review visibly labels LAN and cloud sources',
      (tester) async {
    final repository = _ReviewRepository();
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: ExecutionReviewScreen(repository: repository),
      ),
    );
    await tester.pumpAndSettle();

    expect(repository.lastLimit, 50);
    expect(find.text('局域网'), findsOneWidget);
    expect(find.text('云中继'), findsOneWidget);
    expect(find.textContaining('本地执行'), findsOneWidget);
    expect(find.textContaining('云端执行'), findsOneWidget);
  });

  testWidgets('execution review keeps local cards when cloud history fails',
      (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: ExecutionReviewScreen(
          repository: _PartialSyncReviewRepository(),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('云端历史暂未同步'), findsOneWidget);
    expect(find.textContaining('保留的本地执行'), findsOneWidget);
    expect(find.textContaining('暂时无法连接电脑端'), findsNothing);
  });

  testWidgets('execution review turns timeout into a retryable product state',
      (tester) async {
    final repository = _TimeoutReviewRepository();
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: ExecutionReviewScreen(repository: repository),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('暂时无法加载执行记录'), findsOneWidget);
    expect(find.textContaining('连接电脑端超时'), findsOneWidget);
    expect(find.textContaining('TimeoutException'), findsNothing);
    expect(find.text('重新加载'), findsOneWidget);

    await tester.tap(find.text('重新加载'));
    await tester.pumpAndSettle();
    expect(repository.loadCalls, 2);
  });

  testWidgets('chat history labels sources and exposes archive action',
      (tester) async {
    final repository = _ChatHistoryRepository();
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: ChatScreen(
          conversation: _codexConversation,
          initialMessages: const [],
          repository: repository,
        ),
      ),
    );
    await tester.pumpAndSettle();

    await tester.tap(find.byTooltip('更多工具'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('新建对话'));
    await tester.pumpAndSettle();

    expect(find.text('局域网 · 待命'), findsOneWidget);
    expect(find.text('云中继 · 待命'), findsOneWidget);
    await tester.tap(find.byTooltip('对话操作').first);
    await tester.pumpAndSettle();
    expect(find.text('归档对话'), findsOneWidget);
  });
}

const _lanSession = MobileSessionData(
  serverMode: 'lan',
  localAccessToken: 'desktop-jwt',
  localBaseUrl: 'http://192.168.10.2:17500/fhd-api',
);

const _codexConversation = ConversationItem(
  id: PinnedIds.codex,
  type: ConversationType.pinnedCodex,
  title: '超级员工-Codex',
  subtitle: '',
  timestampText: '',
);

class _LanTaskApi extends MobileApiClient {
  _LanTaskApi(
    MobileSessionStore store, {
    this.includeCloudRun = false,
    this.cloudHistoryFailure = false,
    this.blockStreamUntilCancelled = false,
    this.cancelAck = true,
    this.semanticStreamError = false,
  }) : super(sessionStore: store);

  final bool includeCloudRun;
  final bool cloudHistoryFailure;
  final bool blockStreamUntilCancelled;
  final bool cancelAck;
  final bool semanticStreamError;
  final Completer<void> streamStarted = Completer<void>();
  final List<Map<String, Object?>> streamContexts = [];
  int streamCalls = 0;
  int directCalls = 0;
  int localCancelCalls = 0;
  int relayCancelCalls = 0;
  int relayArchiveCalls = 0;
  String lastCancelPath = '';

  @override
  Future<String> streamSuperEmployeeMessage(
    String tool,
    String body, {
    String baseUrl = '',
    void Function(String token)? onToken,
    void Function(String status)? onStatus,
    bool Function()? isCancelled,
    Map<String, Object?> context = const {},
  }) async {
    streamCalls += 1;
    streamContexts.add(Map<String, Object?>.from(context));
    if (!streamStarted.isCompleted) streamStarted.complete();
    onStatus?.call('电脑正在执行');
    if (semanticStreamError) {
      throw const MobileApiException(
        statusCode: 200,
        message: 'Codex 当前用量已耗尽，请稍后重试',
        body: {
          'type': 'error',
          'error_code': 'usage_limit',
        },
      );
    }
    if (blockStreamUntilCancelled) {
      while (!(isCancelled?.call() ?? false)) {
        await Future<void>.delayed(const Duration(milliseconds: 1));
      }
      return '';
    }
    final reply = '局域网回复 $streamCalls';
    onToken?.call(reply);
    return reply;
  }

  @override
  Future<MobileEnvelope<Map<String, Object?>>> postSuperEmployeeMessage(
    String tool,
    String body, {
    String baseUrl = '',
    Map<String, Object?> context = const {},
  }) async {
    directCalls += 1;
    return const MobileEnvelope<Map<String, Object?>>(
      success: true,
      message: '',
      data: {
        'assistant_message': {'body': '不应调用直答回退'},
      },
      raw: {},
    );
  }

  @override
  Future<Map<String, Object?>> postJson(
    String path,
    Map<String, Object?> body, {
    Map<String, String> query = const {},
    String? baseUrl,
  }) async {
    if (path.contains('/admin/super-employee/tasks/') &&
        path.endsWith('/cancel')) {
      localCancelCalls += 1;
      lastCancelPath = path;
      return {
        'success': true,
        'data': {'ack': cancelAck},
      };
    }
    throw StateError('unexpected POST $path');
  }

  @override
  Future<MobileEnvelope<Map<String, Object?>>> relayThreads({
    String employeeId = '',
    bool includeArchived = false,
    int limit = 100,
  }) async {
    return const MobileEnvelope<Map<String, Object?>>(
      success: true,
      message: '',
      data: {'items': []},
      raw: {},
    );
  }

  @override
  Future<MobileEnvelope<Map<String, Object?>>> relayTasks({
    String threadId = '',
    bool activeOnly = false,
    int limit = 100,
  }) async {
    if (cloudHistoryFailure) {
      throw TimeoutException('云端执行历史超时');
    }
    return MobileEnvelope<Map<String, Object?>>(
      success: true,
      message: '',
      data: {
        'items': [
          if (includeCloudRun)
            const {
              'task_id': 'cloud-run-1',
              'thread_id': 'cloud-thread-1',
              'employee_id': 'codex-super-employee',
              'kind': 'codex.invoke',
              'status': 'completed',
              'attempt_no': 1,
              'created_at': '2026-07-10T00:00:00Z',
              'updated_at': '2026-07-10T00:01:00Z',
              'payload': {'message': '云端任务'},
              'result': {'reply': '云端回复'},
            },
        ],
      },
      raw: const {},
    );
  }

  @override
  Future<MobileEnvelope<Map<String, Object?>>> relayCancelTask(
    String taskId,
  ) async {
    relayCancelCalls += 1;
    return const MobileEnvelope<Map<String, Object?>>(
      success: true,
      message: '',
      data: {
        'task': {'status': 'cancelled'},
      },
      raw: {},
    );
  }

  @override
  Future<MobileEnvelope<Map<String, Object?>>> relayArchiveThread(
    String threadId,
  ) async {
    relayArchiveCalls += 1;
    return const MobileEnvelope<Map<String, Object?>>(
      success: true,
      message: '',
      data: {},
      raw: {},
    );
  }
}

class _ReviewRepository extends MobileRepository {
  _ReviewRepository()
      : super(
          client: MobileApiClient(
            sessionStore: MemoryMobileSessionStore(_lanSession),
          ),
        );

  int lastLimit = 0;

  @override
  Future<List<RelayRunSummary>> loadRelayRuns({
    String threadId = '',
    bool activeOnly = false,
    int limit = 100,
    void Function()? onCloudSyncFailed,
  }) async {
    lastLimit = limit;
    return const [
      RelayRunSummary(
        taskId: 'local-review',
        threadId: 'local-thread',
        workItemId: 'local-work',
        employeeId: 'codex-super-employee',
        kind: 'codex.invoke',
        status: 'completed',
        attemptNo: 1,
        createdAt: '2026-07-10T00:00:00Z',
        updatedAt: '2026-07-10T00:01:00Z',
        message: '本地执行',
        source: 'lan',
      ),
      RelayRunSummary(
        taskId: 'cloud-review',
        threadId: 'cloud-thread',
        workItemId: 'cloud-work',
        employeeId: 'codex-super-employee',
        kind: 'codex.invoke',
        status: 'completed',
        attemptNo: 1,
        createdAt: '2026-07-10T00:00:00Z',
        updatedAt: '2026-07-10T00:01:00Z',
        message: '云端执行',
        source: 'cloud',
      ),
    ];
  }
}

class _PartialSyncReviewRepository extends _ReviewRepository {
  @override
  Future<List<RelayRunSummary>> loadRelayRuns({
    String threadId = '',
    bool activeOnly = false,
    int limit = 100,
    void Function()? onCloudSyncFailed,
  }) async {
    onCloudSyncFailed?.call();
    return const [
      RelayRunSummary(
        taskId: 'local-partial-review',
        threadId: 'local-thread',
        workItemId: 'local-work',
        employeeId: 'codex-super-employee',
        kind: 'codex.invoke',
        status: 'completed',
        attemptNo: 1,
        createdAt: '2026-07-10T00:00:00Z',
        updatedAt: '2026-07-10T00:01:00Z',
        message: '保留的本地执行',
        source: 'lan',
      ),
    ];
  }
}

class _TimeoutReviewRepository extends MobileRepository {
  _TimeoutReviewRepository()
      : super(
          client: MobileApiClient(
            sessionStore: MemoryMobileSessionStore(_lanSession),
          ),
        );

  int loadCalls = 0;

  @override
  Future<List<RelayRunSummary>> loadRelayRuns({
    String threadId = '',
    bool activeOnly = false,
    int limit = 100,
    void Function()? onCloudSyncFailed,
  }) async {
    loadCalls += 1;
    throw TimeoutException('Future not completed');
  }
}

class _ChatHistoryRepository extends MobileRepository {
  _ChatHistoryRepository()
      : super(
          client: MobileApiClient(
            sessionStore: MemoryMobileSessionStore(
              const MobileSessionData(
                activeSuperEmployeeThreads: {
                  PinnedIds.codex: 'local-history',
                },
              ),
            ),
          ),
        );

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
  Future<List<RelayRunSummary>> loadRelayRuns({
    String threadId = '',
    bool activeOnly = false,
    int limit = 100,
    void Function()? onCloudSyncFailed,
  }) async =>
      const [];

  @override
  Future<List<SuperEmployeeThread>> loadSuperEmployeeThreads(
    ConversationItem conversation, {
    bool includeArchived = false,
  }) async {
    return const [
      SuperEmployeeThread(
        threadId: 'local-history',
        employeeId: 'codex-super-employee',
        tool: 'codex',
        title: '局域网历史',
        status: 'idle',
        updatedAt: '2026-07-10T00:01:00Z',
        source: 'lan',
      ),
      SuperEmployeeThread(
        threadId: 'cloud-history',
        employeeId: 'codex-super-employee',
        tool: 'codex',
        title: '云端历史',
        status: 'idle',
        updatedAt: '2026-07-10T00:00:00Z',
        source: 'cloud',
      ),
    ];
  }
}
