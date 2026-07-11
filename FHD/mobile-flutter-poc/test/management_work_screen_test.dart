import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_api.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_models.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_session_store.dart';
import 'package:xcagi_flutter_poc/src/data/mobile_repository.dart';
import 'package:xcagi_flutter_poc/src/features/employees/management_work_screen.dart';
import 'package:xcagi_flutter_poc/src/theme/app_theme.dart';

void main() {
  testWidgets('enterprise account cannot enter the management work surface',
      (tester) async {
    final api = _FakeManagementApi(
      session: const MobileSessionData(
        accountKind: 'enterprise',
        localAccessToken: 'local-token',
        localSessionId: 'local-session',
        localAccountKind: 'admin',
        localTokenScope: 'management_pairing',
      ),
    );

    await _pumpScreen(tester, api);

    expect(find.textContaining('仅向管理端管理员开放'), findsOneWidget);
    expect(api.listCalls, 0);
  });

  testWidgets('admin without management pairing gets a fail-fast pairing state',
      (tester) async {
    final api = _FakeManagementApi(
      session: const MobileSessionData(
        accountKind: 'admin',
        localAccessToken: 'enterprise-token',
        localSessionId: 'enterprise-session',
        localAccountKind: 'enterprise',
        localTokenScope: 'enterprise_pairing',
      ),
    );

    await _pumpScreen(tester, api);

    expect(find.textContaining('管理端手机配对'), findsOneWidget);
    expect(find.text('重新检查连接'), findsOneWidget);
    expect(api.listCalls, 0);
  });

  testWidgets('deep link renders a filtered terminal task and its proof',
      (tester) async {
    final api = _FakeManagementApi(
      session: _managementSession,
      detail: _failedTask,
      listItems: const [],
    );

    await _pumpScreen(tester, api, initialTaskId: 'mwi_failed');

    expect(find.text('发布移动端管理功能'), findsOneWidget);
    expect(find.text('验收标准（必须核对）'), findsOneWidget);
    expect(find.textContaining('需通过真机验证'), findsOneWidget);
    expect(find.text('执行证据'), findsOneWidget);
    expect(find.textContaining('截图已保存'), findsOneWidget);
    expect(find.text('交付产物'), findsOneWidget);
    expect(find.textContaining('release.apk'), findsOneWidget);
  });

  testWidgets(
      'acceptance stays disabled without a current-attempt PASS receipt',
      (tester) async {
    final api = _FakeManagementApi(
      session: _managementSession,
      detail: _deliveredWithoutCurrentReceipt,
      listItems: const [],
    );

    await _pumpScreen(tester, api, initialTaskId: 'mwi_receipt_missing');

    expect(find.text('独立验收回执'), findsOneWidget);
    expect(find.textContaining('尚无独立验收回执'), findsOneWidget);
    expect(find.textContaining('历史回执（不可授权当前验收）'), findsOneWidget);
    final accept = tester.widget<FilledButton>(
      find.widgetWithText(FilledButton, '验收通过'),
    );
    expect(accept.onPressed, isNull);
    final reject = tester.widget<OutlinedButton>(
      find.widgetWithText(OutlinedButton, '退回返工'),
    );
    expect(reject.onPressed, isNotNull);
  });

  testWidgets('current PASS receipt still blocks unresolved operation recovery',
      (tester) async {
    final api = _FakeManagementApi(
      session: _managementSession,
      detail: _deliveredWithCurrentReceipt,
      listItems: const [],
    );

    await _pumpScreen(tester, api, initialTaskId: 'mwi_receipt_pass');

    expect(find.text('独立事实证据'), findsOneWidget);
    expect(find.textContaining('事实核验通过 · 有效至'), findsOneWidget);
    expect(find.textContaining('file · apk_sha'), findsOneWidget);
    expect(find.textContaining('PASS · 独立验收通过'), findsOneWidget);
    expect(find.text('副作用操作与恢复状态'), findsOneWidget);
    expect(
      find.text('第 2 次执行 · 外部结果不确定 · 自动恢复失败'),
      findsOneWidget,
    );
    expect(find.textContaining('operation-rollback-error'), findsOneWidget);
    expect(
      find.textContaining('尚未收口：外部结果仍不确定；自动恢复失败'),
      findsOneWidget,
    );
    final accept = tester.widget<FilledButton>(
      find.widgetWithText(FilledButton, '验收通过'),
    );
    expect(accept.onPressed, isNull);
  });

  testWidgets(
      'acceptance enables only when receipt facts and operations are safe',
      (tester) async {
    final api = _FakeManagementApi(
      session: _managementSession,
      detail: _deliveredReadyForAcceptance,
      listItems: const [],
    );

    await _pumpScreen(tester, api, initialTaskId: 'mwi_accept_ready');

    expect(find.textContaining('可以进入老板验收'), findsOneWidget);
    expect(find.textContaining('没有待恢复项'), findsOneWidget);
    final accept = tester.widget<FilledButton>(
      find.widgetWithText(FilledButton, '验收通过'),
    );
    expect(accept.onPressed, isNotNull);
  });

  testWidgets('backend details are replaced with a safe product error',
      (tester) async {
    final api = _FakeManagementApi(
      session: _managementSession,
      listError: const MobileApiException(
        statusCode: 502,
        message: 'Connection refused http://127.0.0.1:8788 secret-path',
        body: {'code': 'upstream_failed'},
      ),
    );

    await _pumpScreen(tester, api);

    expect(find.textContaining('管理端任务服务暂时不可用'), findsOneWidget);
    expect(find.textContaining('127.0.0.1'), findsNothing);
    expect(find.textContaining('secret-path'), findsNothing);
  });

  testWidgets('attention snackbar does not cover chat after leaving inbox', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(430, 1800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final api = _FakeManagementApi(
      session: _managementSession,
      detail: _attentionTask,
      listItems: [
        <String, Object?>{
          ..._attentionTask,
          'updated_at': '2026-07-10T10:00:00Z',
        },
      ],
    );

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: Builder(
          builder: (context) => Scaffold(
            body: Column(
              children: [
                const TextField(key: ValueKey('underlying_chat_composer')),
                TextButton(
                  onPressed: () => Navigator.of(context).push<void>(
                    MaterialPageRoute(
                      builder: (_) => ManagementWorkScreen(
                        repository: MobileRepository(client: api),
                      ),
                    ),
                  ),
                  child: const Text('打开员工待办'),
                ),
              ],
            ),
          ),
        ),
      ),
    );

    await tester.tap(find.text('打开员工待办'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 40));

    api.listItems = [
      <String, Object?>{
        ..._attentionTask,
        'updated_at': '2026-07-10T10:05:00Z',
      },
    ];
    await tester.pump(const Duration(seconds: 5));
    await tester.pump(const Duration(milliseconds: 40));

    expect(find.textContaining('等待老板决策：'), findsOneWidget);

    await tester.tap(find.byTooltip('返回'));
    await tester.pumpAndSettle();

    expect(
      find.byKey(const ValueKey('underlying_chat_composer')),
      findsOneWidget,
    );
    expect(find.textContaining('等待老板决策：'), findsNothing);
  });
}

const _attentionTask = <String, Object?>{
  'task_id': 'mwi_attention',
  'title': '等待老板决策',
  'owner_employee_id': 'release-officer',
  'status': 'waiting_decision',
  'current_stage': 'waiting_owner_decision',
  'attempt_count': 1,
  'max_attempts': 3,
  'updated_at': '2026-07-10T10:00:00Z',
  'decisions': [
    {
      'decision_id': 'mdc_attention',
      'question': '是否继续执行？',
      'status': 'pending',
      'requested_at': '2026-07-10T10:00:00Z',
      'due_at': '2026-07-10T11:00:00Z',
    },
  ],
  'events': <Object?>[],
};

const _managementSession = MobileSessionData(
  accountKind: 'admin',
  userId: 9,
  localAccessToken: 'management-token',
  localSessionId: 'management-session',
  localAccountKind: 'admin',
  localTokenScope: 'management_pairing',
  localUserId: 9,
  localBaseUrl: 'http://192.168.10.2:17500/fhd-api',
  fhdHost: '192.168.10.2:17500',
);

const _failedTask = <String, Object?>{
  'task_id': 'mwi_failed',
  'title': '发布移动端管理功能',
  'description': '完成企业端与管理端隔离',
  'owner_employee_id': 'fhd-core-maintainer',
  'status': 'failed',
  'priority': 'P0',
  'risk_level': 'high',
  'acceptance_required': true,
  'acceptance_criteria': ['需通过真机验证'],
  'progress': 80,
  'current_stage': 'release-smoke',
  'error': '签名包尚未生成',
  'artifacts': [
    {'name': 'release.apk', 'sha256': 'abc123'},
  ],
  'evidence': [
    {'summary': '截图已保存'},
  ],
  'updated_at': '2026-07-10T12:00:00Z',
  'decisions': <Object?>[],
  'events': <Object?>[],
};

const _deliveredWithoutCurrentReceipt = <String, Object?>{
  'task_id': 'mwi_receipt_missing',
  'title': '历史回执不能授权新一轮验收',
  'owner_employee_id': 'fhd-core-maintainer',
  'status': 'delivered',
  'attempt_count': 2,
  'max_attempts': 3,
  'result_summary': '第 2 次执行已提交结果',
  'verification_receipts': [
    {
      'receipt_id': 'mvr_attempt_1',
      'task_id': 'mwi_receipt_missing',
      'attempt': 1,
      'result_digest': 'old-result-digest',
      'fact_bundle_digest': 'old-fact-digest',
      'fact_outcome': 'pass',
      'audit_outcome': 'pass',
      'status': 'pass',
      'verifier_employee_id': 'delivery-receipt-officer',
    },
  ],
  'fact_evidence': <Object?>[],
  'operations': <Object?>[],
  'decisions': <Object?>[],
  'events': <Object?>[],
};

const _deliveredWithCurrentReceipt = <String, Object?>{
  'task_id': 'mwi_receipt_pass',
  'title': '当前轮次事实与恢复状态',
  'owner_employee_id': 'release-officer',
  'status': 'delivered',
  'attempt_count': 2,
  'max_attempts': 3,
  'result_summary': '第 2 次执行已提交且独立核验通过',
  'fact_evidence': [
    {
      'evidence_id': 'mwe_current',
      'task_id': 'mwi_receipt_pass',
      'attempt': 2,
      'check_id': 'apk_sha',
      'criterion_ids': ['criterion_release'],
      'kind': 'file',
      'trust_level': 'independent_observation',
      'status': 'pass',
      'source_ref': '/safe/release.apk',
      'observed_at': '2026-07-10T12:00:00Z',
      'expires_at': '2099-07-10T12:00:00Z',
      'payload': {
        'verified': true,
        'strength': 'strong',
        'checks': {'exists': true, 'sha256': true},
      },
      'payload_sha256': '1234567890abcdef1234567890abcdef',
      'signature': 'signed',
    },
  ],
  'verification_receipts': [
    {
      'receipt_id': 'mvr_attempt_2',
      'task_id': 'mwi_receipt_pass',
      'attempt': 2,
      'result_digest': 'result-digest-current',
      'fact_bundle_digest': 'fact-digest-current',
      'fact_required': true,
      'fact_outcome': 'pass',
      'audit_outcome': 'pass',
      'status': 'pass',
      'verifier_employee_id': 'delivery-receipt-officer',
      'audit': {'reason': '全部验收标准都有独立事实支持'},
    },
  ],
  'operations': [
    {
      'operation_id': 'mop_release',
      'operation_key': 'mop_key_release',
      'task_id': 'mwi_receipt_pass',
      'employee_id': 'release-officer',
      'task_revision': 1,
      'logical_step': 'publish-artifact',
      'attempt': 2,
      'kind': 'file.write',
      'target': '/safe/release.json',
      'request_digest': 'request-digest-current',
      'status': 'uncertain',
      'reversible': true,
      'compensation_status': 'failed',
      'error': 'operation-rollback-error',
    },
  ],
  'decisions': <Object?>[],
  'events': <Object?>[],
};

const _deliveredReadyForAcceptance = <String, Object?>{
  'task_id': 'mwi_accept_ready',
  'title': '全部门禁已经满足',
  'owner_employee_id': 'release-officer',
  'status': 'delivered',
  'attempt_count': 3,
  'max_attempts': 3,
  'result_summary': '当前轮次事实、回执和副作用均已收口',
  'fact_evidence': [
    {
      'evidence_id': 'mwe_ready',
      'task_id': 'mwi_accept_ready',
      'attempt': 3,
      'check_id': 'release_hash',
      'criterion_ids': ['criterion_release'],
      'kind': 'file',
      'trust_level': 'independent_observation',
      'status': 'pass',
      'source_ref': '/safe/release.apk',
      'observed_at': '2026-07-10T12:00:00Z',
      'expires_at': '2099-07-10T12:00:00Z',
      'payload': {'verified': true, 'strength': 'strong'},
      'payload_sha256': 'ready-evidence-digest',
      'signature': 'signed',
    },
  ],
  'verification_receipts': [
    {
      'receipt_id': 'mvr_attempt_3',
      'task_id': 'mwi_accept_ready',
      'attempt': 3,
      'result_digest': 'ready-result-digest',
      'fact_bundle_digest': 'ready-fact-digest',
      'fact_required': true,
      'fact_outcome': 'pass',
      'audit_outcome': 'pass',
      'status': 'pass',
      'verifier_employee_id': 'delivery-receipt-officer',
    },
  ],
  'operations': [
    {
      'operation_id': 'mop_ready',
      'operation_key': 'mop_key_ready',
      'task_id': 'mwi_accept_ready',
      'employee_id': 'release-officer',
      'task_revision': 1,
      'logical_step': 'publish-artifact',
      'attempt': 3,
      'kind': 'file.write',
      'target': '/safe/release.json',
      'request_digest': 'request-digest-ready',
      'status': 'succeeded',
      'reversible': true,
      'compensation_status': 'available',
    },
  ],
  'decisions': <Object?>[],
  'events': <Object?>[],
};

Future<void> _pumpScreen(
  WidgetTester tester,
  _FakeManagementApi api, {
  String? initialTaskId,
}) async {
  tester.view.physicalSize = const Size(430, 1800);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  await tester.pumpWidget(
    MaterialApp(
      theme: AppTheme.light(),
      home: ManagementWorkScreen(
        repository: MobileRepository(client: api),
        initialTaskId: initialTaskId,
      ),
    ),
  );
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 20));
  await tester.pump(const Duration(milliseconds: 20));
}

class _FakeManagementApi extends MobileApiClient {
  _FakeManagementApi({
    required MobileSessionData session,
    this.detail = _failedTask,
    this.listItems = const [],
    this.listError,
  }) : super(sessionStore: MemoryMobileSessionStore(session));

  final Map<String, Object?> detail;
  List<Map<String, Object?>> listItems;
  final Object? listError;
  int listCalls = 0;

  @override
  Future<MobileEnvelope<Map<String, Object?>>> managementWorkItems({
    String status = '',
    String ownerEmployeeId = '',
    int limit = 100,
  }) async {
    listCalls += 1;
    final error = listError;
    if (error != null) throw error;
    return MobileEnvelope(
      success: true,
      message: '',
      data: {
        'items': listItems,
        'summary': const {
          'by_status': <String, int>{},
          'active': 0,
          'pending_decisions': 0,
          'accepted': 0,
          'blocked': 0,
        },
      },
      raw: const {},
    );
  }

  @override
  Future<MobileEnvelope<Map<String, Object?>>> managementWorkDetail(
    String taskId,
  ) async {
    return MobileEnvelope(
      success: true,
      message: '',
      data: detail,
      raw: const {},
    );
  }

  @override
  Future<MobileEnvelope<Map<String, Object?>>> managementWorkEmployees() async {
    return const MobileEnvelope(
      success: true,
      message: '',
      data: {'employees': <Object?>[]},
      raw: {},
    );
  }
}
