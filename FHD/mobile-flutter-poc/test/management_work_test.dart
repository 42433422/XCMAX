import 'package:flutter_test/flutter_test.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_api.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_session_store.dart';
import 'package:xcagi_flutter_poc/src/data/management_work.dart';
import 'package:xcagi_flutter_poc/src/platform/android_deep_link_bridge.dart';

void main() {
  test('management work parses one persistent task and pending decision', () {
    final item = ManagementWorkItem.fromJson({
      'task_id': 'mwi_same_on_desktop_and_mobile',
      'title': '完成移动端通知',
      'owner_employee_id': 'fhd-core-maintainer',
      'status': 'waiting_decision',
      'priority': 'P0',
      'risk_level': 'high',
      'acceptance_required': true,
      'acceptance_criteria': ['需展示可核验证据'],
      'progress': 62,
      'attempt_count': 1,
      'max_attempts': 3,
      'decisions': [
        {
          'decision_id': 'mdc_1',
          'question': '是否立即发布？',
          'options': ['发布', '暂缓'],
          'status': 'pending',
        },
      ],
      'events': [
        {'id': 1, 'event_type': 'task.created'},
      ],
    });

    expect(item.taskId, 'mwi_same_on_desktop_and_mobile');
    expect(item.needsAttention, isTrue);
    expect(item.pendingDecision?.decisionId, 'mdc_1');
    expect(item.statusLabel, '等你决策');
    expect(item.riskLevel, 'high');
    expect(item.acceptanceCriteria, ['需展示可核验证据']);
  });

  test('management work API paths encode identifiers', () {
    expect(
      XcagiMobileEndpoints.adminManagementWorkDetail('mwi/a b'),
      'api/mobile/v1/admin/employee-work/mwi%2Fa%20b',
    );
    expect(
      XcagiMobileEndpoints.adminManagementDecisionResolve('mdc/a b'),
      'api/mobile/v1/admin/employee-work/decisions/mdc%2Fa%20b/resolve',
    );
    expect(
      XcagiMobileEndpoints.adminManagementWorkCancel('mwi/a b'),
      'api/mobile/v1/admin/employee-work/mwi%2Fa%20b/cancel',
    );
    expect(
      XcagiMobileEndpoints.adminManagementWorkReassign('mwi/a b'),
      'api/mobile/v1/admin/employee-work/mwi%2Fa%20b/reassign',
    );
  });

  test(
      'only a strict PASS receipt for the current attempt authorizes acceptance',
      () {
    final item = ManagementWorkItem.fromJson({
      'task_id': 'mwi_receipt_gate',
      'title': '验证交付门禁',
      'status': 'delivered',
      'attempt_count': 2,
      'verification_receipts': [
        {
          'receipt_id': 'mvr_old',
          'task_id': 'mwi_receipt_gate',
          'attempt': 1,
          'result_digest': 'old-result',
          'fact_outcome': 'pass',
          'audit_outcome': 'pass',
          'status': 'pass',
        },
        {
          'receipt_id': 'mvr_current',
          'task_id': 'mwi_receipt_gate',
          'attempt': 2,
          'result_digest': 'current-result',
          'fact_bundle_digest': 'fact-bundle',
          'fact_outcome': 'pass',
          'audit_outcome': 'pass',
          'status': 'pass',
          'verifier_employee_id': 'delivery-receipt-officer',
        },
      ],
    });

    expect(item.currentAttemptVerificationReceipt?.receiptId, 'mvr_current');
    expect(item.hasCurrentPassingVerificationReceipt, isTrue);
    expect(item.canAcceptDelivery, isTrue);
    expect(item.acceptanceGateMessage, contains('可以进入老板验收'));
  });

  test('historical or failed receipts never authorize the current attempt', () {
    final stale = ManagementWorkItem.fromJson({
      'task_id': 'mwi_stale',
      'title': '历史回执不能复用',
      'status': 'delivered',
      'attempt_count': 2,
      'verification_receipts': [
        {
          'receipt_id': 'mvr_attempt_1',
          'task_id': 'mwi_stale',
          'attempt': 1,
          'result_digest': 'old-result',
          'fact_outcome': 'pass',
          'audit_outcome': 'pass',
          'status': 'pass',
        },
      ],
    });
    final failed = ManagementWorkItem.fromJson({
      'task_id': 'mwi_failed_receipt',
      'title': '当前验收失败',
      'status': 'delivered',
      'attempt_count': 3,
      'verification_receipts': [
        {
          'receipt_id': 'mvr_attempt_3',
          'task_id': 'mwi_failed_receipt',
          'attempt': 3,
          'result_digest': 'current-result',
          'fact_bundle_digest': 'fact-bundle',
          'fact_outcome': 'fail',
          'audit_outcome': 'pass',
          'status': 'fail',
        },
      ],
    });

    expect(stale.hasCurrentPassingVerificationReceipt, isFalse);
    expect(stale.canAcceptDelivery, isFalse);
    expect(stale.acceptanceGateMessage, contains('尚无独立验收回执'));
    expect(failed.hasCurrentPassingVerificationReceipt, isFalse);
    expect(failed.acceptanceGateMessage, contains('事实核验未通过'));
  });

  test('fact evidence and operation recovery truth are typed', () {
    final item = ManagementWorkItem.fromJson({
      'task_id': 'mwi_truth',
      'title': '事实与恢复',
      'status': 'blocked',
      'attempt_count': 2,
      'fact_evidence': [
        {
          'evidence_id': 'mwe_1',
          'task_id': 'mwi_truth',
          'attempt': 2,
          'check_id': 'apk_sha',
          'criterion_ids': ['criterion_1'],
          'kind': 'file',
          'trust_level': 'independent_observation',
          'status': 'pass',
          'source_ref': '/safe/release.apk',
          'payload': {'verified': true, 'strength': 'strong'},
          'payload_sha256': '1234567890abcdef',
        },
      ],
      'operations': [
        {
          'operation_id': 'mop_1',
          'operation_key': 'mop_key',
          'task_id': 'mwi_truth',
          'employee_id': 'release-officer',
          'task_revision': 1,
          'logical_step': 'publish',
          'attempt': 2,
          'kind': 'http.post',
          'target': 'https://example.invalid/release',
          'request_digest': 'request-digest',
          'status': 'uncertain',
          'reversible': false,
          'compensation_status': 'unavailable',
          'error': '远端响应丢失',
        },
      ],
    });

    expect(item.currentAttemptFactEvidence.single.passed, isTrue);
    expect(
        item.currentAttemptFactEvidence.single.criterionIds, ['criterion_1']);
    expect(item.operations.single.statusLabel, '外部结果不确定');
    expect(item.operations.single.recoveryStatusLabel, contains('人工核对'));
    expect(item.operationsNeedingRecovery.single.operationId, 'mop_1');
  });

  test('required facts must all pass and remain unexpired', () {
    ManagementWorkItem itemWithFacts(List<Map<String, Object?>> facts) =>
        ManagementWorkItem.fromJson({
          'task_id': 'mwi_fact_gate',
          'title': '事实有效期门禁',
          'status': 'delivered',
          'attempt_count': 2,
          'verification_receipts': [
            {
              'receipt_id': 'mvr_fact_gate',
              'task_id': 'mwi_fact_gate',
              'attempt': 2,
              'result_digest': 'result-current',
              'fact_bundle_digest': 'facts-current',
              'fact_required': true,
              'fact_outcome': 'pass',
              'audit_outcome': 'pass',
              'status': 'pass',
              'verifier_employee_id': 'delivery-receipt-officer',
            },
          ],
          'fact_evidence': facts,
        });

    final missing = itemWithFacts(const []);
    final failed = itemWithFacts(const [
      {
        'evidence_id': 'mwe_failed',
        'task_id': 'mwi_fact_gate',
        'attempt': 2,
        'check_id': 'runtime_check',
        'trust_level': 'independent_observation',
        'status': 'fail',
        'expires_at': '2099-01-01T00:00:00Z',
        'payload_sha256': 'failed-payload-digest',
        'signature': 'signed',
      },
    ]);
    final expired = itemWithFacts(const [
      {
        'evidence_id': 'mwe_expired',
        'task_id': 'mwi_fact_gate',
        'attempt': 2,
        'check_id': 'artifact_hash',
        'trust_level': 'independent_observation',
        'status': 'pass',
        'expires_at': '2000-01-01T00:00:00Z',
        'payload_sha256': 'expired-payload-digest',
        'signature': 'signed',
      },
    ]);
    final fresh = itemWithFacts(const [
      {
        'evidence_id': 'mwe_fresh',
        'task_id': 'mwi_fact_gate',
        'attempt': 2,
        'check_id': 'artifact_hash',
        'trust_level': 'independent_observation',
        'status': 'pass',
        'expires_at': '2099-01-01T00:00:00Z',
        'payload_sha256': 'fresh-payload-digest',
        'signature': 'signed',
      },
    ]);

    expect(missing.canAcceptDelivery, isFalse);
    expect(missing.acceptanceGateMessage, contains('没有任何事实明细'));
    expect(failed.canAcceptDelivery, isFalse);
    expect(failed.acceptanceGateMessage, contains('runtime_check 未通过'));
    expect(expired.canAcceptDelivery, isFalse);
    expect(expired.acceptanceGateMessage, contains('artifact_hash 已于'));
    expect(fresh.canAcceptDelivery, isTrue);
  });

  test('current facts fail closed when identity or provenance is missing', () {
    ManagementWorkItem itemWithFact(Map<String, Object?> fact) =>
        ManagementWorkItem.fromJson({
          'task_id': 'mwi_fact_shape',
          'title': '事实结构门禁',
          'status': 'delivered',
          'attempt_count': 2,
          'verification_receipts': const [
            {
              'receipt_id': 'mvr_fact_shape',
              'task_id': 'mwi_fact_shape',
              'attempt': 2,
              'result_digest': 'result-current',
              'fact_bundle_digest': 'facts-current',
              'fact_required': true,
              'fact_outcome': 'pass',
              'audit_outcome': 'pass',
              'status': 'pass',
              'verifier_employee_id': 'delivery-receipt-officer',
            },
          ],
          'fact_evidence': [fact],
        });

    const valid = <String, Object?>{
      'evidence_id': 'mwe_shape',
      'task_id': 'mwi_fact_shape',
      'attempt': 2,
      'check_id': 'artifact_hash',
      'trust_level': 'independent_observation',
      'status': 'pass',
      'expires_at': '2099-01-01T00:00:00Z',
      'payload_sha256': 'payload-digest',
      'signature': 'signed',
    };
    final cases = <Map<String, Object?>>[
      {...valid, 'task_id': ''},
      {...valid, 'attempt': 0},
      {...valid, 'trust_level': ''},
      {...valid, 'payload_sha256': ''},
      {...valid, 'signature': ''},
      {...valid, 'expires_at': ''},
    ];
    final expected = <String>[
      '缺少 task_id',
      '缺少有效 attempt',
      'independent_observation',
      '缺少 payload_sha256',
      '缺少独立采集签名',
      '缺少有效到期时间',
    ];

    for (var index = 0; index < cases.length; index += 1) {
      final item = itemWithFact(cases[index]);
      expect(item.canAcceptDelivery, isFalse, reason: 'case $index');
      expect(
        item.acceptanceGateMessage,
        contains(expected[index]),
        reason: 'case $index',
      );
    }
    expect(itemWithFact(valid).canAcceptDelivery, isTrue);
  });

  test('unresolved operation or compensation blocks acceptance', () {
    ManagementWorkItem itemWithOperation(Map<String, Object?> operation) =>
        ManagementWorkItem.fromJson({
          'task_id': 'mwi_operation_gate',
          'title': '副作用恢复门禁',
          'status': 'delivered',
          'attempt_count': 1,
          'verification_receipts': const [
            {
              'receipt_id': 'mvr_operation_gate',
              'task_id': 'mwi_operation_gate',
              'attempt': 1,
              'result_digest': 'result-current',
              'fact_bundle_digest': 'facts-current',
              'fact_outcome': 'pass',
              'audit_outcome': 'pass',
              'status': 'pass',
              'verifier_employee_id': 'delivery-receipt-officer',
            },
          ],
          'operations': [operation],
        });

    final running = itemWithOperation(const {
      'operation_id': 'mop_running',
      'task_id': 'mwi_operation_gate',
      'status': 'running',
      'compensation_status': 'available',
    });
    final recoveryFailed = itemWithOperation(const {
      'operation_id': 'mop_recovery_failed',
      'task_id': 'mwi_operation_gate',
      'status': 'succeeded',
      'compensation_status': 'failed',
    });
    final safe = itemWithOperation(const {
      'operation_id': 'mop_safe',
      'task_id': 'mwi_operation_gate',
      'status': 'succeeded',
      'compensation_status': 'available',
      'reversible': true,
    });

    expect(running.canAcceptDelivery, isFalse);
    expect(running.acceptanceGateMessage, contains('外部动作仍在执行'));
    expect(recoveryFailed.canAcceptDelivery, isFalse);
    expect(recoveryFailed.acceptanceGateMessage, contains('自动恢复失败'));
    expect(safe.canAcceptDelivery, isTrue);
  });

  test('operations fail closed when task or state fields are malformed', () {
    ManagementWorkItem itemWithOperation(Map<String, Object?> operation) =>
        ManagementWorkItem.fromJson({
          'task_id': 'mwi_operation_shape',
          'title': '操作结构门禁',
          'status': 'delivered',
          'attempt_count': 1,
          'verification_receipts': const [
            {
              'receipt_id': 'mvr_operation_shape',
              'task_id': 'mwi_operation_shape',
              'attempt': 1,
              'result_digest': 'result-current',
              'fact_bundle_digest': 'facts-current',
              'fact_outcome': 'pass',
              'audit_outcome': 'pass',
              'status': 'pass',
              'verifier_employee_id': 'delivery-receipt-officer',
            },
          ],
          'operations': [operation],
        });

    const valid = <String, Object?>{
      'operation_id': 'mop_shape',
      'task_id': 'mwi_operation_shape',
      'status': 'succeeded',
      'compensation_status': 'available',
    };
    final cases = <Map<String, Object?>>[
      {...valid, 'task_id': ''},
      {...valid, 'status': ''},
      {...valid, 'status': 'pending'},
      {...valid, 'compensation_status': ''},
      {...valid, 'compensation_status': 'mystery'},
    ];
    final expected = <String>[
      '缺少 task_id',
      '操作状态缺失或未知',
      '操作状态缺失或未知',
      '补偿状态缺失或未知',
      '补偿状态缺失或未知',
    ];

    for (var index = 0; index < cases.length; index += 1) {
      final item = itemWithOperation(cases[index]);
      expect(item.canAcceptDelivery, isFalse, reason: 'case $index');
      expect(
        item.acceptanceGateMessage,
        contains(expected[index]),
        reason: 'case $index',
      );
    }
    expect(itemWithOperation(valid).canAcceptDelivery, isTrue);
  });

  test('foreign current-attempt receipt cannot hide the matching receipt', () {
    final item = ManagementWorkItem.fromJson({
      'task_id': 'mwi_receipt_identity',
      'title': '回执身份绑定',
      'status': 'delivered',
      'attempt_count': 2,
      'verification_receipts': const [
        {
          'receipt_id': 'mvr_matching',
          'task_id': 'mwi_receipt_identity',
          'attempt': 2,
          'result_digest': 'result-current',
          'fact_bundle_digest': 'facts-current',
          'fact_outcome': 'pass',
          'audit_outcome': 'pass',
          'status': 'pass',
          'verifier_employee_id': 'delivery-receipt-officer',
        },
        {
          'receipt_id': 'mvr_foreign',
          'task_id': 'another-task',
          'attempt': 2,
          'result_digest': 'foreign-result',
          'fact_bundle_digest': 'foreign-facts',
          'fact_outcome': 'pass',
          'audit_outcome': 'pass',
          'status': 'pass',
          'verifier_employee_id': 'delivery-receipt-officer',
        },
      ],
    });

    expect(item.currentAttemptVerificationReceipt?.receiptId, 'mvr_matching');
    expect(item.canAcceptDelivery, isTrue);
  });

  test('management cancel and reassign controls follow truthful states', () {
    final running = ManagementWorkItem.fromJson({
      'task_id': 'mwi_running',
      'title': '执行中',
      'owner_employee_id': 'fhd-core-maintainer',
      'status': 'running',
    });
    final stopping = ManagementWorkItem.fromJson({
      'task_id': 'mwi_stopping',
      'title': '正在停止',
      'owner_employee_id': 'fhd-core-maintainer',
      'status': 'cancel_requested',
    });
    final assigned = ManagementWorkItem.fromJson({
      'task_id': 'mwi_assigned',
      'title': '待领取',
      'owner_employee_id': 'daily-orchestrator',
      'status': 'assigned',
      'current_stage': 'reassigned',
    });

    expect(running.canCancel, isTrue);
    expect(running.canReassign, isFalse);
    expect(stopping.statusLabel, '正在安全停止');
    expect(stopping.canCancel, isFalse);
    expect(stopping.needsAttention, isTrue);
    expect(assigned.canReassign, isTrue);
    expect(assigned.needsAttention, isTrue);
  });

  test('management notification deep link preserves task id', () {
    final destination = resolveAndroidDeepLinkDestination(
      'management_work/mwi_same_on_desktop_and_mobile',
    );
    expect(destination.target, AndroidDeepLinkTarget.managementWork);
    expect(destination.taskId, 'mwi_same_on_desktop_and_mobile');
  });

  test('management work prefers paired desktop even while app is cloud mode',
      () {
    const paired = MobileSessionData(
      accessToken: 'cloud-token',
      localAccessToken: 'desktop-token',
      localSessionId: 'desktop-session',
      localAccountKind: 'admin',
      localTokenScope: 'management_pairing',
      accountKind: 'admin',
      userId: 9,
      localUserId: 9,
      localBaseUrl: 'http://192.168.1.20:17500/fhd-api',
      fhdHost: '192.168.1.20:17500',
      serverMode: 'cloud',
    );
    const cloudOnly = MobileSessionData(
      accessToken: 'cloud-token',
      serverMode: 'cloud',
    );

    expect(
      preferredManagementWorkBaseUrlForSession(paired),
      'http://192.168.1.20:17500/',
    );
    expect(preferredManagementWorkBaseUrlForSession(cloudOnly), isNull);
  });

  test('enterprise pairing can never select the management ledger', () {
    const enterprisePairing = MobileSessionData(
      localAccessToken: 'enterprise-token',
      localSessionId: 'enterprise-session',
      localAccountKind: 'enterprise',
      localTokenScope: 'enterprise_pairing',
      localBaseUrl: 'http://192.168.1.20:17500/fhd-api',
      fhdHost: '192.168.1.20:17500',
    );

    expect(enterprisePairing.hasVerifiedManagementPairing, isFalse);
    expect(preferredManagementWorkBaseUrlForSession(enterprisePairing), isNull);
  });

  test('management requests fail fast instead of falling back to cloud',
      () async {
    final client = MobileApiClient(
      sessionStore: MemoryMobileSessionStore(
        const MobileSessionData(
          accessToken: 'cloud-admin-token',
          accountKind: 'admin',
        ),
      ),
    );

    await expectLater(
      client.requireManagementWorkBaseUrl(),
      throwsA(
        isA<MobileApiException>()
            .having((error) => error.statusCode, 'statusCode', 428)
            .having(
              (error) => error.body['code'],
              'code',
              'management_pairing_required',
            ),
      ),
    );
  });

  test('rejected delivery requires actionable feedback', () async {
    final repository = ManagementWorkRepository(MobileApiClient());
    await expectLater(
      repository.review(taskId: 'mwi_1', accepted: false),
      throwsA(
        isA<ManagementWorkException>().having(
          (error) => error.message,
          'message',
          contains('退回返工'),
        ),
      ),
    );
  });

  test('repository refuses acceptance without a current PASS receipt',
      () async {
    final repository = ManagementWorkRepository(MobileApiClient());
    final stale = ManagementWorkItem.fromJson({
      'task_id': 'mwi_guard',
      'title': '保护接受操作',
      'status': 'delivered',
      'attempt_count': 2,
      'verification_receipts': [
        {
          'receipt_id': 'mvr_old',
          'task_id': 'mwi_guard',
          'attempt': 1,
          'result_digest': 'old-result',
          'fact_outcome': 'pass',
          'audit_outcome': 'pass',
          'status': 'pass',
        },
      ],
    });

    await expectLater(
      repository.review(
        taskId: stale.taskId,
        accepted: true,
        item: stale,
      ),
      throwsA(
        isA<ManagementWorkException>().having(
          (error) => error.message,
          'message',
          contains('尚无独立验收回执'),
        ),
      ),
    );
  });

  test('repository rechecks the full acceptance gate before review', () async {
    final repository = ManagementWorkRepository(MobileApiClient());
    final missingFacts = ManagementWorkItem.fromJson({
      'task_id': 'mwi_repository_full_gate',
      'title': '提交前完整门禁',
      'status': 'delivered',
      'attempt_count': 1,
      'verification_receipts': const [
        {
          'receipt_id': 'mvr_repository_full_gate',
          'task_id': 'mwi_repository_full_gate',
          'attempt': 1,
          'result_digest': 'result-current',
          'fact_bundle_digest': 'facts-current',
          'fact_required': true,
          'fact_outcome': 'pass',
          'audit_outcome': 'pass',
          'status': 'pass',
          'verifier_employee_id': 'delivery-receipt-officer',
        },
      ],
      'fact_evidence': const <Object?>[],
      'operations': const <Object?>[],
    });

    await expectLater(
      repository.review(
        taskId: missingFacts.taskId,
        accepted: true,
        item: missingFacts,
      ),
      throwsA(
        isA<ManagementWorkException>().having(
          (error) => error.message,
          'message',
          contains('没有任何事实明细'),
        ),
      ),
    );
  });
}
