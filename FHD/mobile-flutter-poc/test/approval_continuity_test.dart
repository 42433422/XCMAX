import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_api.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_session_store.dart';
import 'package:xcagi_flutter_poc/src/data/mobile_repository.dart';
import 'package:xcagi_flutter_poc/src/features/approval/approval_screens.dart';
import 'package:xcagi_flutter_poc/src/widgets/we_ui.dart';

class _ApprovalRepository extends MobileRepository {
  _ApprovalRepository(this.api) : super(client: api);

  final MobileApiClient api;
  int reads = 0;
  int writes = 0;
  bool pending = true;
  bool loseWriteReceipt = false;

  ApprovalDetail get detail => ApprovalDetail(
        id: 42,
        requestNo: 'REQ-42',
        title: '跨端库存审批',
        status: pending ? 'pending' : 'approved',
        applicantName: '提交人',
        flowName: '库存审批',
        currentNodeName: '审批节点',
        submittedAt: '',
        description: '核对原任务',
      );

  @override
  Future<ApprovalDetail> loadApprovalDetail(int id) async {
    reads++;
    expect(id, 42);
    return detail;
  }

  @override
  Future<void> approveApproval(int id, String opinion) async {
    writes++;
    if (loseWriteReceipt) throw TimeoutException('response lost');
    pending = false;
  }
}

void main() {
  late MobileApiClient api;
  late _ApprovalRepository repo;

  setUp(() {
    api = MobileApiClient(sessionStore:
        MemoryMobileSessionStore(MobileSessionData.empty));
    repo = _ApprovalRepository(api);
  });

  tearDown(() async {
    await repo.dispose();
    api.dispose();
  });

  testWidgets('old initial approval is not enough to authorize a write',
      (tester) async {
    await tester.pumpWidget(MaterialApp(
      home: ApprovalDetailScreen(
        id: 42, repository: repo, initialDetail: repo.detail,
      ),
    ));
    await tester.pumpAndSettle();
    expect(repo.reads, greaterThan(0));
    repo.pending = false;
    await tester.tap(find.text('通过'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('确定'));
    await tester.pumpAndSettle();
    expect(repo.writes, 0);
    expect(find.textContaining('原审批已变更'), findsOneWidget);
  });

  testWidgets('account switch hides cached approval and disables actions',
      (tester) async {
    await tester.pumpWidget(MaterialApp(
      home: ApprovalDetailScreen(
        id: 42, repository: repo, initialDetail: repo.detail,
      ),
    ));
    await tester.pumpAndSettle();
    expect(find.text('跨端库存审批'), findsOneWidget);
    await api.clearActiveAuth();
    await tester.pumpAndSettle();
    expect(find.text('跨端库存审批'), findsNothing);
    expect(find.text('账号已切换，请重新打开审批'), findsOneWidget);
    expect(repo.writes, 0);
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets('lost approval receipt blocks repeated writes',
      (tester) async {
    repo.loseWriteReceipt = true;
    await tester.pumpWidget(MaterialApp(
      home: ApprovalDetailScreen(id: 42, repository: repo),
    ));
    await tester.pumpAndSettle();
    await tester.tap(find.text('通过'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('确定'));
    await tester.pumpAndSettle();
    expect(repo.writes, 1);
    expect(repo.reads, greaterThanOrEqualTo(3));
    expect(find.textContaining('请勿重复操作'), findsOneWidget);
    final submit = tester.widget<WeBlockButton>(
        find.widgetWithText(WeBlockButton, '通过'));
    expect(submit.enabled, isFalse);
    await tester.pumpWidget(const SizedBox());
  });
}
