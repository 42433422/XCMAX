import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:xcagi_flutter_poc/src/data/mobile_repository.dart';
import 'package:xcagi_flutter_poc/src/features/approval/approval_screens.dart';
import 'package:xcagi_flutter_poc/src/theme/app_theme.dart';

import 'employee_workspace_screen_test.dart' as fixture;

class ApprovalRepository extends fixture.Repository {
  ApprovalRepository(super.api);

  final pending = Completer<List<ApprovalRequest>>();

  @override
  Future<List<ApprovalRequest>> loadApprovals() => pending.future;
}

const detail = ApprovalDetail(
  id: 1,
  requestNo: 'A001',
  title: '示例审批',
  status: '待审核',
  applicantName: '示例员工',
  flowName: '',
  currentNodeName: '',
  submittedAt: '',
  description: '',
);

double contrast(Color a, Color b) {
  final x = a.computeLuminance();
  final y = b.computeLuminance();
  return x >= y ? (x + 0.05) / (y + 0.05) : (y + 0.05) / (x + 0.05);
}

void main() {
  for (final dark in [false, true]) {
    testWidgets('approval label and status contrast (dark=$dark)',
        (tester) async {
      final semantics = tester.ensureSemantics();
      addTearDown(semantics.dispose);
      final api = fixture.Api();
      final repo = fixture.Repository(api);
      addTearDown(repo.dispose);
      addTearDown(api.dispose);
      tester.view.physicalSize = const Size(320, 900);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      await tester.pumpWidget(MaterialApp(
        theme: dark ? AppTheme.dark() : AppTheme.light(),
        builder: (context, child) => MediaQuery(
          data: MediaQuery.of(context).copyWith(
            textScaler: TextScaler.linear(2),
            disableAnimations: true,
          ),
          child: child!,
        ),
        home: ApprovalDetailScreen(
          id: detail.id,
          initialDetail: detail,
          repository: repo,
        ),
      ));
      await tester.pumpAndSettle();

      final status = find.text('待审核');
      final text = tester.widget<Text>(status);
      final colors = AppTheme.colors(tester.element(status));
      expect(contrast(text.style!.color!, colors.brandContainer),
          greaterThanOrEqualTo(4.5));
      final field = find.byType(TextField);
      await tester.ensureVisible(field);
      expect(tester.widget<TextField>(field).decoration!.labelText,
          '审批意见（可选）');
      await tester.enterText(field, '示例意见');
      await tester.pumpAndSettle();
      expect(tester.widget<TextField>(field).decoration!.labelText,
          '审批意见（可选）');
      expect(tester.widget<SafeArea>(find.byType(SafeArea).first).bottom,
          isTrue);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
    });
  }

  testWidgets('approval loading is named and errors are live regions',
      (tester) async {
    final semantics = tester.ensureSemantics();
    addTearDown(semantics.dispose);
    final api = fixture.Api();
    final repo = ApprovalRepository(api);
    addTearDown(repo.dispose);
    addTearDown(api.dispose);
    await tester.pumpWidget(MaterialApp(
      home: ApprovalListScreen(repository: repo),
    ));
    expect(
      tester.widget<CircularProgressIndicator>(
        find.byType(CircularProgressIndicator),
      ).semanticsLabel,
      '正在加载待办审批',
    );
    repo.pending.completeError(
      const MobileRepositoryException('审批列表加载失败'),
    );
    await tester.pumpAndSettle();
    expect(find.text('重试'), findsOneWidget);
    expect(
      find.byWidgetPredicate(
        (widget) => widget is Semantics && widget.properties.liveRegion == true,
      ),
      findsWidgets,
    );
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox());
  });
}
