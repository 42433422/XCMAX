import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_models.dart';
import 'package:xcagi_flutter_poc/src/data/mobile_repository.dart';
import 'package:xcagi_flutter_poc/src/features/contacts/employee_questions_screen.dart';
import 'package:xcagi_flutter_poc/src/theme/app_theme.dart';

const _pendingQuestion = EmployeePendingQuestion(
  id: 1,
  employeeId: 'llm-ops-engineer',
  task: '排查生产环境模型延迟',
  question: '预算上限是多少？可以直接扩容推理节点吗？',
  status: 'pending',
  answer: '',
  askedAt: '2026-07-07 09:30',
  answeredAt: '',
  expiresAt: '',
);

const _answeredQuestion = EmployeePendingQuestion(
  id: 2,
  employeeId: 'site-content-editor',
  task: '官网首页文案更新',
  question: '新 Slogan 用 A 版还是 B 版？',
  status: 'answered',
  answer: '用 A 版',
  askedAt: '2026-07-06 15:00',
  answeredAt: '2026-07-06 16:00',
  expiresAt: '',
);

class _FakeQuestionsRepository extends MobileRepository {
  _FakeQuestionsRepository({
    List<EmployeePendingQuestion>? questions,
    this.failLoad = false,
  }) : questions = questions ?? const [];

  List<EmployeePendingQuestion> questions;
  final bool failLoad;
  final List<String?> loadedEmployeeIds = [];
  final List<Map<String, Object?>> answers = [];

  @override
  Future<List<EmployeePendingQuestion>> loadEmployeePendingQuestions({
    bool includeHistory = false,
    String? employeeId,
  }) async {
    loadedEmployeeIds.add(employeeId);
    if (failLoad) {
      throw const MobileRepositoryException('failed to connect to desktop');
    }
    return questions;
  }

  @override
  Future<void> answerEmployeePendingQuestion({
    required int questionId,
    required String answer,
  }) async {
    answers.add({'question_id': questionId, 'answer': answer});
    questions = [
      for (final question in questions)
        if (question.id == questionId) _answeredQuestion else question,
    ];
  }
}

Widget _wrap(Widget child) {
  return MaterialApp(theme: AppTheme.light(), home: child);
}

void main() {
  testWidgets('employee questions list mirrors Android task center layout', (
    WidgetTester tester,
  ) async {
    final repository = _FakeQuestionsRepository(
      questions: const [_pendingQuestion, _answeredQuestion],
    );
    await tester.pumpWidget(
      _wrap(EmployeeQuestionsScreen(repository: repository)),
    );
    await tester.pumpAndSettle();

    expect(find.text('员工任务中心'), findsOneWidget);
    expect(repository.loadedEmployeeIds, [null]);
    expect(find.text('@llm-ops-engineer'), findsOneWidget);
    expect(find.text('待回答'), findsOneWidget);
    expect(find.text('原任务：排查生产环境模型延迟'), findsOneWidget);
    expect(find.text('预算上限是多少？可以直接扩容推理节点吗？'), findsOneWidget);
    expect(find.text('提问时间：2026-07-07 09:30'), findsOneWidget);
    expect(find.text('@site-content-editor'), findsOneWidget);
    expect(find.text('已回答'), findsOneWidget);
    expect(find.text('你之前的回答：用 A 版'), findsOneWidget);
    expect(find.text('回答'), findsOneWidget);
  });

  testWidgets('employee filter uses Android per-employee title and query', (
    WidgetTester tester,
  ) async {
    final repository = _FakeQuestionsRepository(
      questions: const [_pendingQuestion],
    );
    await tester.pumpWidget(
      _wrap(
        EmployeeQuestionsScreen(
          repository: repository,
          employeeId: 'llm-ops-engineer',
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('llm-ops-engineer 的提问'), findsOneWidget);
    expect(repository.loadedEmployeeIds, ['llm-ops-engineer']);
  });

  testWidgets('answer flow posts boss reply like Android', (
    WidgetTester tester,
  ) async {
    final repository = _FakeQuestionsRepository(
      questions: const [_pendingQuestion],
    );
    await tester.pumpWidget(
      _wrap(EmployeeQuestionsScreen(repository: repository)),
    );
    await tester.pumpAndSettle();

    await tester.tap(find.text('回答'));
    await tester.pumpAndSettle();
    expect(find.text('你的回答'), findsOneWidget);
    expect(find.text('取消'), findsOneWidget);

    final sendButton = find.widgetWithText(FilledButton, '发送回答');
    expect(tester.widget<FilledButton>(sendButton).onPressed, isNull);

    await tester.enterText(find.byType(TextField), '预算 2 万，先扩 2 台');
    await tester.pumpAndSettle();
    await tester.tap(sendButton);
    await tester.pumpAndSettle();

    expect(repository.answers, [
      {'question_id': 1, 'answer': '预算 2 万，先扩 2 台'},
    ]);
    expect(find.text('已回答'), findsOneWidget);
    expect(find.text('你之前的回答：用 A 版'), findsOneWidget);
  });

  testWidgets('empty state keeps Android task center wording', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(
      _wrap(EmployeeQuestionsScreen(repository: _FakeQuestionsRepository())),
    );
    await tester.pumpAndSettle();

    expect(find.text('暂无员工主动提问'), findsOneWidget);
    expect(find.text('员工遇到需要老板决策的事会主动在这里问你'), findsOneWidget);
  });

  testWidgets('load failure shows Android retry state', (
    WidgetTester tester,
  ) async {
    final repository = _FakeQuestionsRepository(failLoad: true);
    await tester.pumpWidget(
      _wrap(EmployeeQuestionsScreen(repository: repository)),
    );
    await tester.pumpAndSettle();

    expect(find.textContaining('拉不到员工提问：'), findsOneWidget);
    expect(find.text('重试'), findsOneWidget);

    await tester.tap(find.text('重试'));
    await tester.pumpAndSettle();
    expect(repository.loadedEmployeeIds.length, 2);
  });
}
