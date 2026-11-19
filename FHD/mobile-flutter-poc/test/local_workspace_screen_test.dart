import 'package:drift/native.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:xcagi_flutter_poc/src/data/local_workspace.dart';
import 'package:xcagi_flutter_poc/src/features/workspace/local_workspace_screen.dart';

class _WorkspaceFixture extends LocalWorkspaceController {
  _WorkspaceFixture() : super(executor: NativeDatabase.memory());

  final _records = <LocalWorkspaceRecord>[];
  bool _bound = false;
  LocalWorkspaceOrigin? selectedOrigin;
  String? receivedCode;

  @override
  List<LocalWorkspaceRecord> get records => List.unmodifiable(_records);

  @override
  bool get isBound => _bound;

  @override
  Future<void> open() async {}

  @override
  Future<void> bind(String qr, {required LocalWorkspaceOrigin origin}) async {
    _bound = true;
    selectedOrigin = origin;
    receivedCode = qr;
    notifyListeners();
  }

  @override
  Future<void> unbind() async {
    _bound = false;
    notifyListeners();
  }

  @override
  Future<void> sync() async {}

  @override
  Future<void> save(String kind, Map<String, Object?> data,
      {String? id}) async {
    if (id == null) {
      _records.add(LocalWorkspaceRecord(
        id: 'local-${_records.length}',
        kind: kind,
        data: data,
      ));
    } else {
      final index =
          _records.indexWhere((entry) => entry.kind == kind && entry.id == id);
      _records[index] = LocalWorkspaceRecord(id: id, kind: kind, data: data);
    }
    notifyListeners();
  }
}

Future<_WorkspaceFixture> _showWorkspace(WidgetTester tester) async {
  final controller = _WorkspaceFixture();
  addTearDown(controller.closeDatabase);
  await tester.binding.setSurfaceSize(const Size(360, 720));
  addTearDown(() => tester.binding.setSurfaceSize(null));
  await tester.pumpWidget(
      MaterialApp(home: LocalWorkspaceScreen(controller: controller)));
  await tester.pumpAndSettle();
  return controller;
}

void main() {
  testWidgets(
      'creates and searches customers without a login on a narrow phone',
      (tester) async {
    final controller = await _showWorkspace(tester);
    await tester.tap(find.text('新建客户'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('保存'));
    await tester.pumpAndSettle();
    expect(find.text('请填写客户名称').hitTestable(), findsOneWidget);
    await tester.enterText(find.widgetWithText(TextFormField, '客户名称'), '天府样品店');
    expect(find.text('保存').hitTestable(), findsOneWidget);
    await tester.tap(find.text('保存'));
    await tester.pumpAndSettle();
    expect(controller.records.single.data['name'], '天府样品店');
    expect(find.text('天府样品店'), findsOneWidget);
    await tester.enterText(find.widgetWithText(TextField, '搜索客户'), '不匹配');
    await tester.pumpAndSettle();
    expect(find.text('没有匹配的记录'), findsOneWidget);
    await tester.pumpWidget(const SizedBox.shrink());
    controller.dispose();
  });

  testWidgets('requires an explicit source and keeps records after unbinding',
      (tester) async {
    final controller = await _showWorkspace(tester);
    await controller.save('customer', {'name': '本机客户'});
    await tester.pumpAndSettle();
    await tester.tap(find.text('绑定电脑'));
    await tester.pumpAndSettle();
    final scanButton = find.ancestor(
      of: find.text('扫描配对二维码'),
      matching: find.byWidgetPredicate((widget) => widget is FilledButton),
    );
    expect(tester.widget<FilledButton>(scanButton).onPressed, isNull);
    await tester.tap(find.text('以手机为准'));
    await tester.tap(find.text('粘贴二维码内容'));
    await tester.pumpAndSettle();
    final field = find.widgetWithText(TextField, '二维码内容');
    await tester.ensureVisible(field);
    await tester.enterText(field, 'test-qr');
    final submit = find.text('使用配对内容绑定');
    await tester.ensureVisible(submit);
    await tester.pumpAndSettle();
    await tester.tap(submit);
    await tester.pumpAndSettle();
    expect(controller.selectedOrigin, LocalWorkspaceOrigin.mobile);
    expect(controller.receivedCode, 'test-qr');
    expect(find.text('已绑定电脑'), findsOneWidget);
    await tester.tap(find.text('解除绑定'));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, '解除绑定'));
    await tester.pumpAndSettle();
    expect(controller.isBound, isFalse);
    expect(controller.records.single.data['name'], '本机客户');
    await tester.pumpWidget(const SizedBox.shrink());
    controller.dispose();
  });
}
