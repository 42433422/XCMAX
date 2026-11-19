import 'dart:async';

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

class _ArchiveWorkspaceFixture extends _WorkspaceFixture {
  final _archives = List.generate(
      205,
      (index) => LocalWorkspaceArchive(
            id: 'archive-${204 - index}',
            createdAt: DateTime(2026, 1, 1),
            recordCount: 1,
          ));
  final firstRead = Completer<List<LocalWorkspaceRecord>>();
  final reads = <String>[];
  int _offset = 0;
  bool _failPage = true;

  @override
  int get archiveCount => _archives.length;
  @override
  int get archiveOffset => _offset;
  @override
  List<LocalWorkspaceArchive> get archives =>
      _archives.skip(_offset).take(100).toList();

  @override
  Future<void> loadArchivePage({int offset = 0}) async {
    if (_failPage) {
      _failPage = false;
      throw StateError('synthetic page read failure');
    }
    _offset = offset;
    notifyListeners();
  }

  @override
  Future<List<LocalWorkspaceRecord>> archiveRecords(String id) async {
    reads.add(id);
    if (reads.length == 1) return firstRead.future;
    return [
      LocalWorkspaceRecord(
          id: 'old-customer', kind: 'customer', data: {'name': '旧档客户'})
    ];
  }
}

Future<_WorkspaceFixture> _showWorkspace(WidgetTester tester,
    {_WorkspaceFixture? fixture}) async {
  final controller = fixture ?? _WorkspaceFixture();
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
      'pages all archives and loads details only on expansion with retry',
      (tester) async {
    final controller = _ArchiveWorkspaceFixture();
    await _showWorkspace(tester, fixture: controller);
    await tester.tap(find.text('本机归档（205）'));
    await tester.pumpAndSettle();
    expect(find.text('共 205 份归档'), findsOneWidget);
    expect(find.text('1–100'), findsOneWidget);
    expect(controller.reads, isEmpty);
    await tester.tap(find.text('下一页'));
    await tester.pumpAndSettle();
    expect(find.text('无法读取归档列表'), findsOneWidget);
    await tester.tap(find.text('重试'));
    await tester.pumpAndSettle();
    expect(find.text('101–200'), findsOneWidget);
    await tester.tap(find.text('下一页'));
    await tester.pumpAndSettle();
    expect(find.text('201–205'), findsOneWidget);
    expect(controller.reads, isEmpty);

    final oldest = find.byKey(const ValueKey('archive-0'));
    await tester.ensureVisible(oldest);
    await tester.tap(oldest);
    await tester.pump(const Duration(milliseconds: 300));
    expect(controller.reads, ['archive-0']);
    expect(find.text('正在读取归档内容'), findsOneWidget);
    controller.firstRead
        .completeError(StateError('synthetic detail read failure'));
    await tester.pumpAndSettle();
    expect(find.text('无法读取归档内容'), findsOneWidget);
    final retry = find.text('重试');
    await tester.ensureVisible(retry);
    await tester.tap(retry);
    await tester.pumpAndSettle();
    expect(controller.reads, ['archive-0', 'archive-0']);
    expect(find.text('旧档客户'), findsWidgets);
    expect(find.text('恢复此归档'), findsOneWidget);
    await tester.tap(find.text('上一页'));
    await tester.pumpAndSettle();
    expect(find.text('101–200'), findsOneWidget);
    expect(find.text('旧档客户'), findsNothing);
    expect(controller.reads, hasLength(2));
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox.shrink());
    controller.dispose();
  });

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
