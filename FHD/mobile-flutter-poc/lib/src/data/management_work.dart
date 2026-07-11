import '../api/mobile_api.dart';

/// One persistent management-side task shared by desktop, mobile and the worker.
class ManagementWorkItem {
  const ManagementWorkItem({
    required this.taskId,
    required this.title,
    required this.description,
    required this.ownerEmployeeId,
    required this.status,
    required this.priority,
    required this.riskLevel,
    required this.acceptanceRequired,
    required this.acceptanceCriteria,
    required this.progress,
    required this.currentStage,
    required this.lastUpdate,
    required this.resultSummary,
    required this.error,
    required this.attemptCount,
    required this.maxAttempts,
    required this.artifacts,
    required this.evidence,
    required this.factEvidence,
    required this.verificationReceipts,
    required this.operations,
    required this.updatedAt,
    required this.heartbeatAt,
    required this.decisions,
    required this.events,
  });

  final String taskId;
  final String title;
  final String description;
  final String ownerEmployeeId;
  final String status;
  final String priority;
  final String riskLevel;
  final bool acceptanceRequired;
  final List<Object?> acceptanceCriteria;
  final int progress;
  final String currentStage;
  final String lastUpdate;
  final String resultSummary;
  final String error;
  final int attemptCount;
  final int maxAttempts;
  final List<Object?> artifacts;
  final List<Object?> evidence;
  final List<ManagementFactEvidence> factEvidence;
  final List<ManagementVerificationReceipt> verificationReceipts;
  final List<ManagementWorkOperation> operations;
  final String updatedAt;
  final String heartbeatAt;
  final List<ManagementDecision> decisions;
  final List<ManagementWorkEvent> events;

  bool get needsAttention =>
      currentStage == 'reassigned' ||
      const {
        'waiting_decision',
        'delivered',
        'blocked',
        'failed',
        'cancel_requested',
        'cancelled',
      }.contains(status);

  bool get isTerminal => const {'accepted', 'cancelled'}.contains(status);
  bool get canCancel =>
      !const {'accepted', 'cancelled', 'cancel_requested'}.contains(status);
  bool get canReassign => const {
        'assigned',
        'retrying',
        'waiting_decision',
        'blocked',
        'failed',
      }.contains(status);

  ManagementDecision? get pendingDecision {
    for (final decision in decisions.reversed) {
      if (decision.status == 'pending') return decision;
    }
    return null;
  }

  List<ManagementFactEvidence> get currentAttemptFactEvidence => factEvidence
      .where((row) => row.attempt == attemptCount)
      .toList(growable: false);

  ManagementVerificationReceipt? get currentAttemptVerificationReceipt {
    for (final receipt in verificationReceipts.reversed) {
      if (receipt.attempt == attemptCount && receipt.taskId == taskId) {
        return receipt;
      }
    }
    return null;
  }

  bool get hasCurrentPassingVerificationReceipt {
    final receipt = currentAttemptVerificationReceipt;
    return attemptCount > 0 && receipt != null && receipt.isStrictPass;
  }

  bool get hasAcceptableCurrentFactEvidence {
    final receipt = currentAttemptVerificationReceipt;
    if (receipt == null || attemptCount <= 0) return false;
    if (factEvidence.any(
      (fact) =>
          fact.taskId.isEmpty || fact.taskId != taskId || fact.attempt <= 0,
    )) {
      return false;
    }
    final facts = currentAttemptFactEvidence;
    if (receipt.factRequired && facts.isEmpty) return false;
    return facts.every(
      (fact) => fact.isAcceptableForTaskAttempt(taskId, attemptCount),
    );
  }

  bool get hasUnresolvedOperations => operationsNeedingRecovery.isNotEmpty;

  bool get canAcceptDelivery =>
      status == 'delivered' &&
      hasCurrentPassingVerificationReceipt &&
      hasAcceptableCurrentFactEvidence &&
      !hasUnresolvedOperations;

  String get acceptanceGateMessage {
    if (status != 'delivered') {
      return '任务当前为$statusLabel，只有已交付状态才能进入老板验收。';
    }
    final receipt = currentAttemptVerificationReceipt;
    if (receipt == null) {
      return '第 $attemptCount 次执行尚无独立验收回执，暂不能接受交付。';
    }
    if (!hasCurrentPassingVerificationReceipt) {
      return '第 $attemptCount 次执行的独立验收回执不可信：${receipt.strictPassBlockReason}。';
    }
    for (final fact in factEvidence) {
      final identity = fact.checkId.ifEmpty(fact.evidenceId).ifEmpty('未编号事实');
      if (fact.taskId.isEmpty) {
        return '事实证据 $identity 缺少 task_id，暂不能接受交付。';
      }
      if (fact.taskId != taskId) {
        return '事实证据 $identity 不属于当前任务，暂不能接受交付。';
      }
      if (fact.attempt <= 0) {
        return '事实证据 $identity 缺少有效 attempt，暂不能接受交付。';
      }
    }
    final facts = currentAttemptFactEvidence;
    if (receipt.factRequired && facts.isEmpty) {
      return '第 $attemptCount 次执行要求独立事实证据，但当前没有任何事实明细，暂不能接受交付。';
    }
    for (final fact in facts) {
      final identity = fact.checkId.ifEmpty(fact.evidenceId).ifEmpty('未编号事实');
      if (!fact.passed) {
        return '事实证据 $identity 未通过，暂不能接受交付。';
      }
      if (fact.trustLevel.toLowerCase() != 'independent_observation') {
        return '事实证据 $identity 缺少可信的 independent_observation 标记。';
      }
      if (fact.payloadSha256.isEmpty) {
        return '事实证据 $identity 缺少 payload_sha256，无法确认内容未被替换。';
      }
      if (fact.signature.isEmpty) {
        return '事实证据 $identity 缺少独立采集签名，暂不能接受交付。';
      }
      if (!fact.hasParseableExpiry) {
        return '事实证据 $identity 缺少有效到期时间，无法确认仍然有效。';
      }
      if (fact.isExpired) {
        return '事实证据 $identity 已于 ${fact.expiresAt} 过期，请重新核验后再接受。';
      }
    }
    if (operationsNeedingRecovery.isNotEmpty) {
      final operation = operationsNeedingRecovery.first;
      return '副作用操作 ${operation.operationId.ifEmpty(operation.logicalStep).ifEmpty('未编号操作')} 尚未收口：${operation.acceptanceBlockReasonForTask(taskId)}。';
    }
    return '第 $attemptCount 次执行已有独立 PASS 回执，可以进入老板验收。';
  }

  List<ManagementWorkOperation> get operationsNeedingRecovery => operations
      .where((operation) => operation.blocksAcceptanceForTask(taskId))
      .toList(growable: false);

  String get statusLabel => switch (status) {
        'assigned' => '待领取',
        'running' => '执行中',
        'cancel_requested' => '正在安全停止',
        'waiting_decision' => '等你决策',
        'retrying' => '等待重试',
        'verifying' => '验证中',
        'delivered' => '等待验收',
        'accepted' => '已验收',
        'blocked' => '已阻塞',
        'failed' => '失败',
        'cancelled' => '已取消',
        _ => status,
      };

  factory ManagementWorkItem.fromJson(Map<String, Object?> json) {
    return ManagementWorkItem(
      taskId: _string(json['task_id']),
      title: _string(json['title']),
      description: _string(json['description']),
      ownerEmployeeId: _string(json['owner_employee_id']),
      status: _string(json['status']),
      priority: _string(json['priority']).ifEmpty('P1'),
      riskLevel: _string(json['risk_level']).ifEmpty('medium'),
      acceptanceRequired: _boolean(json['acceptance_required'], fallback: true),
      acceptanceCriteria: _list(json['acceptance_criteria']),
      progress: _integer(json['progress']).clamp(0, 100),
      currentStage: _string(json['current_stage']),
      lastUpdate: _string(json['last_update']),
      resultSummary: _string(json['result_summary']),
      error: _string(json['error']),
      attemptCount: _integer(json['attempt_count']),
      maxAttempts: _integer(json['max_attempts']),
      artifacts: _list(json['artifacts']),
      evidence: _list(json['evidence']),
      factEvidence: _objectList(json['fact_evidence'])
          .map(ManagementFactEvidence.fromJson)
          .toList(growable: false),
      verificationReceipts: _objectList(json['verification_receipts'])
          .map(ManagementVerificationReceipt.fromJson)
          .toList(growable: false),
      operations: _objectList(json['operations'])
          .map(ManagementWorkOperation.fromJson)
          .toList(growable: false),
      updatedAt: _string(json['updated_at']),
      heartbeatAt: _string(json['heartbeat_at']),
      decisions: _objectList(json['decisions'])
          .map(ManagementDecision.fromJson)
          .toList(growable: false),
      events: _objectList(json['events'])
          .map(ManagementWorkEvent.fromJson)
          .toList(growable: false),
    );
  }
}

/// An observation collected outside the employee process.
class ManagementFactEvidence {
  const ManagementFactEvidence({
    required this.evidenceId,
    required this.taskId,
    required this.attempt,
    required this.checkId,
    required this.criterionIds,
    required this.kind,
    required this.trustLevel,
    required this.status,
    required this.sourceRef,
    required this.observedAt,
    required this.expiresAt,
    required this.collectorVersion,
    required this.payload,
    required this.payloadSha256,
    required this.signature,
  });

  final String evidenceId;
  final String taskId;
  final int attempt;
  final String checkId;
  final List<String> criterionIds;
  final String kind;
  final String trustLevel;
  final String status;
  final String sourceRef;
  final String observedAt;
  final String expiresAt;
  final String collectorVersion;
  final Map<String, Object?> payload;
  final String payloadSha256;
  final String signature;

  bool get passed => status.toLowerCase() == 'pass';

  DateTime? get expiry => _timestamp(expiresAt);

  bool get hasParseableExpiry => expiry != null;

  bool get isExpired {
    final value = expiry;
    return value == null || !value.isAfter(DateTime.now().toUtc());
  }

  bool get hasValidFutureExpiry => hasParseableExpiry && !isExpired;

  bool get hasTrustedProvenance =>
      trustLevel.toLowerCase() == 'independent_observation' &&
      payloadSha256.isNotEmpty &&
      signature.isNotEmpty;

  bool isAcceptableForTaskAttempt(String expectedTaskId, int expectedAttempt) =>
      taskId == expectedTaskId &&
      attempt == expectedAttempt &&
      passed &&
      hasTrustedProvenance &&
      hasValidFutureExpiry;

  String get statusLabel => passed ? '事实核验通过' : '事实核验失败';

  factory ManagementFactEvidence.fromJson(Map<String, Object?> json) {
    return ManagementFactEvidence(
      evidenceId: _string(json['evidence_id']),
      taskId: _string(json['task_id']),
      attempt: _integer(json['attempt']),
      checkId: _string(json['check_id']),
      criterionIds: _list(json['criterion_ids'])
          .map(_string)
          .where((value) => value.isNotEmpty)
          .toList(growable: false),
      kind: _string(json['kind']),
      trustLevel: _string(json['trust_level']),
      status: _string(json['status']),
      sourceRef: _string(json['source_ref']),
      observedAt: _string(json['observed_at']),
      expiresAt: _string(json['expires_at']),
      collectorVersion: _string(json['collector_version']),
      payload: _map(json['payload']),
      payloadSha256: _string(json['payload_sha256']),
      signature: _string(json['signature']),
    );
  }
}

/// Immutable independent-verifier receipt for exactly one execution attempt.
class ManagementVerificationReceipt {
  const ManagementVerificationReceipt({
    required this.receiptId,
    required this.taskId,
    required this.attempt,
    required this.resultDigest,
    required this.factBundleDigest,
    required this.factRequired,
    required this.factOutcome,
    required this.auditOutcome,
    required this.status,
    required this.verifierEmployeeId,
    required this.audit,
    required this.createdAt,
  });

  final String receiptId;
  final String taskId;
  final int attempt;
  final String resultDigest;
  final String factBundleDigest;
  final bool factRequired;
  final String factOutcome;
  final String auditOutcome;
  final String status;
  final String verifierEmployeeId;
  final Map<String, Object?> audit;
  final String createdAt;

  bool get passed => status.toLowerCase() == 'pass';

  bool get isStrictPass =>
      receiptId.isNotEmpty &&
      resultDigest.isNotEmpty &&
      factBundleDigest.isNotEmpty &&
      status.toLowerCase() == 'pass' &&
      factOutcome.toLowerCase() == 'pass' &&
      auditOutcome.toLowerCase() == 'pass' &&
      verifierEmployeeId == 'delivery-receipt-officer';

  String get strictPassBlockReason {
    if (receiptId.isEmpty) return '缺少 receipt_id';
    if (resultDigest.isEmpty) return '缺少 result_digest';
    if (factBundleDigest.isEmpty) return '缺少 fact_bundle_digest';
    if (factOutcome.toLowerCase() != 'pass') return '事实核验未通过';
    if (auditOutcome.toLowerCase() != 'pass') return '语义验收未通过';
    if (status.toLowerCase() != 'pass') return '回执状态不是 PASS';
    if (verifierEmployeeId != 'delivery-receipt-officer') {
      return '验收员不是 delivery-receipt-officer';
    }
    return '回执字段不完整';
  }

  String get statusLabel => passed ? 'PASS · 独立验收通过' : 'FAIL · 独立验收未通过';

  String get factOutcomeLabel => _outcomeLabel(factOutcome);

  String get auditOutcomeLabel => _outcomeLabel(auditOutcome);

  String get reason => _string(audit['reason']);

  factory ManagementVerificationReceipt.fromJson(Map<String, Object?> json) {
    return ManagementVerificationReceipt(
      receiptId: _string(json['receipt_id']),
      taskId: _string(json['task_id']),
      attempt: _integer(json['attempt']),
      resultDigest: _string(json['result_digest']),
      factBundleDigest: _string(json['fact_bundle_digest']),
      factRequired: _boolean(json['fact_required'], fallback: false),
      factOutcome: _string(json['fact_outcome']),
      auditOutcome: _string(json['audit_outcome']),
      status: _string(json['status']),
      verifierEmployeeId: _string(json['verifier_employee_id']),
      audit: _map(json['audit']),
      createdAt: _string(json['created_at']),
    );
  }
}

/// One idempotent external side-effect and its compensation/recovery truth.
class ManagementWorkOperation {
  const ManagementWorkOperation({
    required this.operationId,
    required this.operationKey,
    required this.taskId,
    required this.employeeId,
    required this.taskRevision,
    required this.logicalStep,
    required this.attempt,
    required this.kind,
    required this.target,
    required this.requestDigest,
    required this.status,
    required this.reversible,
    required this.externalRef,
    required this.result,
    required this.error,
    required this.compensationStatus,
    required this.compensation,
    required this.leaseExpiresAt,
    required this.createdAt,
    required this.updatedAt,
    required this.completedAt,
  });

  final String operationId;
  final String operationKey;
  final String taskId;
  final String employeeId;
  final int taskRevision;
  final String logicalStep;
  final int attempt;
  final String kind;
  final String target;
  final String requestDigest;
  final String status;
  final bool reversible;
  final String externalRef;
  final Map<String, Object?> result;
  final String error;
  final String compensationStatus;
  final Map<String, Object?> compensation;
  final String leaseExpiresAt;
  final String createdAt;
  final String updatedAt;
  final String completedAt;

  bool get needsRecoveryAttention =>
      !hasKnownStatus ||
      !hasKnownCompensationStatus ||
      const {'running', 'uncertain'}.contains(status.toLowerCase()) ||
      const {'required', 'failed', 'conflict', 'unavailable'}
          .contains(compensationStatus.toLowerCase());

  bool get hasKnownStatus => const {
        'running',
        'succeeded',
        'failed',
        'uncertain',
      }.contains(status.toLowerCase());

  bool get hasKnownCompensationStatus => const {
        'not_required',
        'available',
        'required',
        'compensated',
        'failed',
        'conflict',
        'unavailable',
      }.contains(compensationStatus.toLowerCase());

  bool blocksAcceptanceForTask(String expectedTaskId) =>
      taskId.isEmpty || taskId != expectedTaskId || needsRecoveryAttention;

  String acceptanceBlockReasonForTask(String expectedTaskId) {
    if (taskId.isEmpty) return '缺少 task_id';
    if (taskId != expectedTaskId) return 'task_id 与当前任务不一致';
    return acceptanceBlockReason;
  }

  String get acceptanceBlockReason {
    final normalizedStatus = status.toLowerCase();
    final reasons = <String>[];
    if (!hasKnownStatus) reasons.add('操作状态缺失或未知');
    if (normalizedStatus == 'running') reasons.add('外部动作仍在执行');
    if (normalizedStatus == 'uncertain') reasons.add('外部结果仍不确定');
    if (!hasKnownCompensationStatus) reasons.add('补偿状态缺失或未知');
    final recovery = switch (compensationStatus.toLowerCase()) {
      'required' => '等待恢复',
      'failed' => '自动恢复失败',
      'conflict' => '恢复与后续修改冲突',
      'unavailable' => '无法自动恢复，需人工核对',
      _ => '',
    };
    if (recovery.isNotEmpty) reasons.add(recovery);
    return reasons.isEmpty ? 'operation 尚未完成安全收口' : reasons.join('；');
  }

  String get statusLabel => switch (status.toLowerCase()) {
        'running' => '执行中，结果待确认',
        'succeeded' => '已确认成功',
        'failed' => '已确认未生效',
        'uncertain' => '外部结果不确定',
        _ => status.ifEmpty('未知状态'),
      };

  String get recoveryStatusLabel {
    if (compensationStatus.toLowerCase() == 'not_required' &&
        status.toLowerCase() == 'succeeded' &&
        !reversible) {
      return '已确认生效，不支持自动恢复';
    }
    return switch (compensationStatus.toLowerCase()) {
      'not_required' => '无需恢复',
      'available' => '保留可恢复快照',
      'required' => '等待恢复',
      'compensated' => '已安全恢复',
      'failed' => '自动恢复失败',
      'conflict' => '检测到后续修改，拒绝覆盖',
      'unavailable' => '无法自动恢复，需人工核对',
      _ => compensationStatus.ifEmpty('未登记恢复状态'),
    };
  }

  factory ManagementWorkOperation.fromJson(Map<String, Object?> json) {
    return ManagementWorkOperation(
      operationId: _string(json['operation_id']),
      operationKey: _string(json['operation_key']),
      taskId: _string(json['task_id']),
      employeeId: _string(json['employee_id']),
      taskRevision: _integer(json['task_revision']),
      logicalStep: _string(json['logical_step']),
      attempt: _integer(json['attempt']),
      kind: _string(json['kind']),
      target: _string(json['target']),
      requestDigest: _string(json['request_digest']),
      status: _string(json['status']),
      reversible: _boolean(json['reversible'], fallback: false),
      externalRef: _string(json['external_ref']),
      result: _map(json['result']),
      error: _string(json['error']),
      compensationStatus: _string(json['compensation_status']),
      compensation: _map(json['compensation']),
      leaseExpiresAt: _string(json['lease_expires_at']),
      createdAt: _string(json['created_at']),
      updatedAt: _string(json['updated_at']),
      completedAt: _string(json['completed_at']),
    );
  }
}

class ManagementDecision {
  const ManagementDecision({
    required this.decisionId,
    required this.question,
    required this.options,
    required this.recommendation,
    required this.status,
    required this.decision,
    required this.dueAt,
  });

  final String decisionId;
  final String question;
  final List<Object?> options;
  final String recommendation;
  final String status;
  final String decision;
  final String dueAt;

  factory ManagementDecision.fromJson(Map<String, Object?> json) {
    return ManagementDecision(
      decisionId: _string(json['decision_id']),
      question: _string(json['question']),
      options: _list(json['options']),
      recommendation: _string(json['recommendation']),
      status: _string(json['status']),
      decision: _string(json['decision']),
      dueAt: _string(json['due_at']),
    );
  }
}

class ManagementWorkEvent {
  const ManagementWorkEvent({
    required this.id,
    required this.eventType,
    required this.actorType,
    required this.message,
    required this.createdAt,
  });

  final int id;
  final String eventType;
  final String actorType;
  final String message;
  final String createdAt;

  String get label => switch (eventType) {
        'task.created' => '任务创建',
        'task.routed' => '智能选人',
        'task.claimed' => '员工领取',
        'task.progress' => '进度汇报',
        'decision.requested' => '请求决策',
        'decision.resolved' => '决策已回复',
        'decision.cancelled' => '决策已取消',
        'decision.superseded' => '原决策已作废',
        'task.retry_scheduled' => '安排重试',
        'task.verification_receipt' => '独立验收回执',
        'task.delivered' => '提交交付',
        'task.accepted' => '验收通过',
        'task.rejected' => '退回返工',
        'task.blocked' => '升级人工',
        'task.cancel_requested' => '请求安全停止',
        'task.cancelled' => '任务已停止',
        'task.reassigned' => '任务已改派',
        'task.side_effect_recovery_required' => '副作用恢复待处理',
        'operation.started' => '副作用操作开始',
        'operation.replayed' => '复用幂等操作结果',
        'operation.reclaimed' => '回收操作租约',
        'operation.succeeded' => '副作用操作成功',
        'operation.failed' => '副作用操作失败',
        'operation.uncertain' => '副作用结果不确定',
        'operation.compensated' => '副作用已恢复',
        _ => eventType,
      };

  factory ManagementWorkEvent.fromJson(Map<String, Object?> json) {
    return ManagementWorkEvent(
      id: _integer(json['id']),
      eventType: _string(json['event_type']),
      actorType: _string(json['actor_type']),
      message: _string(json['message']),
      createdAt: _string(json['created_at']),
    );
  }
}

class ManagementWorkSummary {
  const ManagementWorkSummary({
    required this.byStatus,
    required this.active,
    required this.pendingDecisions,
    required this.accepted,
    required this.blocked,
  });

  final Map<String, int> byStatus;
  final int active;
  final int pendingDecisions;
  final int accepted;
  final int blocked;

  int get delivered => byStatus['delivered'] ?? 0;

  factory ManagementWorkSummary.fromJson(Map<String, Object?> json) {
    final rawByStatus = _map(json['by_status']);
    return ManagementWorkSummary(
      byStatus: rawByStatus.map(
        (key, value) => MapEntry(key, _integer(value)),
      ),
      active: _integer(json['active']),
      pendingDecisions: _integer(json['pending_decisions']),
      accepted: _integer(json['accepted']),
      blocked: _integer(json['blocked']),
    );
  }
}

class ManagementDutyEmployee {
  const ManagementDutyEmployee({
    required this.employeeId,
    required this.name,
    required this.area,
    required this.manifestRegistered,
    required this.runtimeExecutable,
    required this.primaryAssignable,
    required this.runtimeIssues,
  });

  final String employeeId;
  final String name;
  final String area;
  final bool manifestRegistered;
  final bool runtimeExecutable;
  final bool primaryAssignable;
  final List<String> runtimeIssues;

  factory ManagementDutyEmployee.fromJson(Map<String, Object?> json) {
    return ManagementDutyEmployee(
      employeeId: _string(json['employee_id']),
      name: _string(json['name']),
      area: _string(json['area']),
      manifestRegistered: json['manifest_registered'] == true,
      runtimeExecutable: json['runtime_executable'] == true,
      primaryAssignable: json['primary_assignable'] == true,
      runtimeIssues: _list(json['runtime_issues'])
          .map((value) => _string(value))
          .where((value) => value.isNotEmpty)
          .toList(growable: false),
    );
  }
}

class ManagementWorkSnapshot {
  const ManagementWorkSnapshot({required this.items, required this.summary});

  final List<ManagementWorkItem> items;
  final ManagementWorkSummary summary;
}

class ManagementWorkRepository {
  ManagementWorkRepository(this.client);

  final MobileApiClient client;

  Future<ManagementWorkSnapshot> load({
    String status = '',
    int limit = 200,
  }) async {
    final response = await client.managementWorkItems(
      status: status,
      limit: limit,
    );
    if (!response.success) {
      throw ManagementWorkException(
        response.message.ifEmpty('员工任务加载失败'),
      );
    }
    final data = response.data ?? const <String, Object?>{};
    final items = _objectList(data['items'])
        .map(ManagementWorkItem.fromJson)
        .where((item) => item.taskId.isNotEmpty)
        .toList(growable: false);
    return ManagementWorkSnapshot(
      items: items,
      summary: ManagementWorkSummary.fromJson(_map(data['summary'])),
    );
  }

  Future<ManagementWorkItem> detail(String taskId) async {
    final response = await client.managementWorkDetail(taskId);
    if (!response.success) {
      throw ManagementWorkException(response.message.ifEmpty('任务详情加载失败'));
    }
    final item = ManagementWorkItem.fromJson(
      response.data ?? const <String, Object?>{},
    );
    if (item.taskId.isEmpty) {
      throw const ManagementWorkException('任务详情缺少 task_id');
    }
    return item;
  }

  Future<List<ManagementDutyEmployee>> employees() async {
    final response = await client.managementWorkEmployees();
    if (!response.success) {
      throw ManagementWorkException(response.message.ifEmpty('管理编制加载失败'));
    }
    final data = response.data ?? const <String, Object?>{};
    return _objectList(data['employees'])
        .map(ManagementDutyEmployee.fromJson)
        .where((employee) =>
            employee.employeeId.isNotEmpty && employee.primaryAssignable)
        .toList(growable: false);
  }

  Future<void> resolveDecision({
    required String decisionId,
    required String decision,
  }) async {
    if (decision.trim().isEmpty) {
      throw const ManagementWorkException('决定不能为空');
    }
    final response = await client.resolveManagementDecision(
      decisionId: decisionId,
      decision: decision,
    );
    if (!response.success) {
      throw ManagementWorkException(response.message.ifEmpty('回复决策失败'));
    }
  }

  Future<void> review({
    required String taskId,
    required bool accepted,
    String feedback = '',
    ManagementWorkItem? item,
  }) async {
    if (!accepted && feedback.trim().isEmpty) {
      throw const ManagementWorkException('退回返工时请填写需要修改的内容');
    }
    if (accepted &&
        (item == null || item.taskId != taskId || !item.canAcceptDelivery)) {
      throw ManagementWorkException(
        item?.acceptanceGateMessage ?? '缺少当前执行轮次的独立 PASS 验收回执，暂不能接受交付。',
      );
    }
    final response = await client.reviewManagementWork(
      taskId: taskId,
      accepted: accepted,
      feedback: feedback,
    );
    if (!response.success) {
      throw ManagementWorkException(response.message.ifEmpty('验收提交失败'));
    }
  }

  Future<void> retry(String taskId) async {
    final response = await client.retryManagementWork(
      taskId: taskId,
      note: '老板从手机端重新派发',
    );
    if (!response.success) {
      throw ManagementWorkException(response.message.ifEmpty('重新派发失败'));
    }
  }

  Future<void> cancel(String taskId, {String reason = ''}) async {
    final response = await client.cancelManagementWork(
      taskId: taskId,
      reason: reason,
    );
    if (!response.success) {
      throw ManagementWorkException(response.message.ifEmpty('停止任务失败'));
    }
  }

  Future<void> reassign({
    required String taskId,
    required String newEmployeeId,
    String reason = '',
  }) async {
    if (newEmployeeId.trim().isEmpty) {
      throw const ManagementWorkException('请选择新负责人');
    }
    final response = await client.reassignManagementWork(
      taskId: taskId,
      newEmployeeId: newEmployeeId,
      reason: reason,
    );
    if (!response.success) {
      throw ManagementWorkException(response.message.ifEmpty('改派任务失败'));
    }
  }
}

String managementWorkUserMessage(Object error) {
  if (error is ManagementWorkException) return error.message;
  if (error is MobileApiException) {
    final code = error.body['code']?.toString().trim() ?? '';
    if (code == 'management_pairing_required' || error.statusCode == 428) {
      return '尚未连接管理端电脑，请在电脑端打开“管理端手机配对”后重新扫码。';
    }
    if (error.statusCode == 401) return '管理端连接已失效，请重新扫码配对。';
    if (error.statusCode == 403) return '当前账号没有管理员工任务的权限。';
    if (error.statusCode == 404) return '任务已不存在或已被其他管理员处理。';
    if (error.statusCode == 409) return '任务状态已经变化，请刷新后再操作。';
    if (error.statusCode >= 500) return '管理端任务服务暂时不可用，请确认电脑在线后重试。';
    final message = error.message.trim();
    if (message.isNotEmpty && message.length <= 120) return message;
  }
  return '操作没有完成，请确认电脑在线并重试。';
}

class ManagementWorkException implements Exception {
  const ManagementWorkException(this.message);

  final String message;

  @override
  String toString() => message;
}

Map<String, Object?> _map(Object? value) {
  if (value is Map<String, Object?>) return value;
  if (value is Map) {
    return value.map((key, item) => MapEntry('$key', item));
  }
  return const <String, Object?>{};
}

List<Map<String, Object?>> _objectList(Object? value) {
  return _list(value).map(_map).where((item) => item.isNotEmpty).toList();
}

List<Object?> _list(Object? value) {
  return value is List ? List<Object?>.from(value) : const <Object?>[];
}

int _integer(Object? value) {
  if (value is int) return value;
  if (value is num) return value.toInt();
  return int.tryParse('$value') ?? 0;
}

bool _boolean(Object? value, {required bool fallback}) {
  if (value is bool) return value;
  if (value is num) return value != 0;
  final normalized = value?.toString().trim().toLowerCase() ?? '';
  if (const {'true', '1', 'yes', 'on'}.contains(normalized)) return true;
  if (const {'false', '0', 'no', 'off'}.contains(normalized)) return false;
  return fallback;
}

String _string(Object? value) => value?.toString().trim() ?? '';

String _outcomeLabel(String raw) => switch (raw.trim().toLowerCase()) {
      'pass' => '通过',
      'fail' => '失败',
      'invalid' => '无效',
      'inconclusive' => '证据不足',
      _ => raw.trim().isEmpty ? '未提供' : raw.trim(),
    };

DateTime? _timestamp(String raw) {
  final value = raw.trim();
  if (value.isEmpty) return null;
  try {
    return DateTime.parse(value).toUtc();
  } on FormatException {
    return null;
  }
}

extension on String {
  String ifEmpty(String fallback) => isEmpty ? fallback : this;
}
