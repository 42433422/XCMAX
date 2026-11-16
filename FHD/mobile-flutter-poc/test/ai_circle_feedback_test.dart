import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_api.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_models.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_session_store.dart';
import 'package:xcagi_flutter_poc/src/data/ai_employee_profile.dart';
import 'package:xcagi_flutter_poc/src/data/mobile_repository.dart';
import 'package:xcagi_flutter_poc/src/features/circle/ai_circle_screen.dart';
import 'package:xcagi_flutter_poc/src/theme/app_theme.dart';

class _CircleRepository extends MobileRepository {
  _CircleRepository()
      : super(
            client: MobileApiClient(sessionStore: MemoryMobileSessionStore()));
  var like = Completer<void>();
  var comment = Completer<void>();
  var likes = 0;
  var comments = 0;
  Future<List<AiCirclePost>> Function()? readPosts;
  var post = AiCirclePost.fromJson({
    'id': 1,
    'author_name': '小C',
    'body': '已完成巡检',
    'comments': <Object?>[],
  });
  @override
  Future<MobileMeData> loadMe() async => MobileMeData.adminFallback();
  @override
  Future<List<AiEmployeeProfile>> loadAiEmployees() async => [];
  @override
  Future<List<AiCirclePost>> loadAiCirclePosts() async {
    if (readPosts != null) return readPosts!();
    return [post];
  }

  @override
  Future<void> toggleAiCircleLike(int postId) async {
    likes++;
    await like.future;
  }

  @override
  Future<void> addAiCircleComment(int postId, String body) async {
    comments++;
    await comment.future;
    post = post.copyWith(comments: [
      AiCircleComment(id: 2, authorName: '我', body: body, createdAt: '')
    ]);
  }
}

Future<void> _show(WidgetTester tester, _CircleRepository repository,
    {bool reduceMotion = false}) async {
  tester.view.physicalSize = const Size(430, 1200);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  await tester.pumpWidget(MaterialApp(
    theme: AppTheme.light(),
    builder: (context, child) => MediaQuery(
      data: MediaQuery.of(context).copyWith(disableAnimations: reduceMotion),
      child: child!,
    ),
    home: AiCircleScreen(repository: repository),
  ));
  await tester.pumpAndSettle();
  addTearDown(() async {
    await tester.pumpWidget(const SizedBox.shrink());
    await tester.runAsync(() async {
      await repository.dispose();
      repository.client.dispose();
    });
  });
}

void main() {
  testWidgets('initial load failure shows retry instead of empty success',
      (tester) async {
    final repository = _CircleRepository()
      ..readPosts = () async => throw const MobileRepositoryException('网络不可用');
    await _show(tester, repository);
    expect(find.text('动态加载失败'), findsOneWidget);
    expect(find.text('暂无动态'), findsNothing);
    repository.readPosts = null;
    await tester.tap(find.text('重试'));
    await tester.pumpAndSettle();
    expect(find.text('已完成巡检'), findsOneWidget);
    expect(find.text('动态加载失败'), findsNothing);
  });

  testWidgets('refresh failure preserves loaded posts and unsent draft',
      (tester) async {
    final repository = _CircleRepository();
    await _show(tester, repository);
    await tester.tap(find.text('评论'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField), '保留这份草稿');
    repository.readPosts =
        () async => throw const MobileRepositoryException('网络不可用');
    await tester
        .widget<RefreshIndicator>(find.byType(RefreshIndicator))
        .onRefresh();
    await tester.pumpAndSettle();
    expect(find.text('已完成巡检'), findsOneWidget);
    expect(find.text('保留这份草稿'), findsOneWidget);
    expect(find.text('动态更新失败，已保留当前内容'), findsOneWidget);
    expect(find.text('暂无动态'), findsNothing);
  });

  testWidgets('accepted comment clears draft even when follow-up refresh fails',
      (tester) async {
    final repository = _CircleRepository();
    await _show(tester, repository);
    await tester.tap(find.text('评论'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField), '已经提交');
    repository.readPosts =
        () async => throw const MobileRepositoryException('网络不可用');
    await tester.tap(find.text('发送'));
    repository.comment.complete();
    await tester.pumpAndSettle();
    expect(repository.comments, 1);
    expect(find.byType(TextField), findsNothing);
    expect(find.text('已完成巡检'), findsOneWidget);
    expect(find.text('动态更新失败，已保留当前内容'), findsOneWidget);
    expect(find.text('评论失败'), findsNothing);
    await tester.tap(find.text('评论'));
    await tester.pumpAndSettle();
    expect(tester.widget<TextField>(find.byType(TextField)).controller!.text,
        isEmpty);
    repository.readPosts = null;
    await tester.tap(find.text('重试'));
    await tester.pumpAndSettle();
    expect(find.text('我：已经提交'), findsOneWidget);
    expect(repository.comments, 1);
  });

  testWidgets('late refresh and failed like cannot overwrite newer comments',
      (tester) async {
    final repository = _CircleRepository();
    await _show(tester, repository);
    await tester.tap(find.text('赞'));
    await tester.pumpAndSettle();
    final stale = Completer<List<AiCirclePost>>();
    repository.readPosts = () => stale.future;
    final oldRefresh = tester
        .widget<RefreshIndicator>(find.byType(RefreshIndicator))
        .onRefresh();
    await tester.pump();
    repository.like.completeError(const MobileRepositoryException('点赞失败'));
    await tester.pumpAndSettle();
    expect(find.text('点赞失败'), findsOneWidget);
    expect(find.byIcon(Icons.favorite_border), findsOneWidget);
    repository.readPosts = () async => [
          repository.post.copyWith(comments: [
            const AiCircleComment(
                id: 3, authorName: '同事', body: '最新回复', createdAt: '')
          ])
        ];
    await tester
        .widget<RefreshIndicator>(find.byType(RefreshIndicator))
        .onRefresh();
    await tester.pumpAndSettle();
    stale.complete([repository.post]);
    await oldRefresh;
    await tester.pumpAndSettle();
    expect(find.text('同事：最新回复'), findsOneWidget);
    expect(find.byIcon(Icons.favorite_border), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  for (final reduceMotion in [false, true]) {
    testWidgets('like rolls back and blocks repeat taps, reduce=$reduceMotion',
        (tester) async {
      final repository = _CircleRepository();
      await _show(tester, repository, reduceMotion: reduceMotion);
      await tester.tap(find.text('赞'));
      await tester.pumpAndSettle();
      expect(find.text('赞 1'), findsOneWidget);
      expect(repository.likes, 1);
      await tester.tap(find.text('赞 1'));
      await tester.pump();
      expect(repository.likes, 1);
      final switcher = tester.widget<AnimatedSwitcher>(find.ancestor(
          of: find.byIcon(Icons.favorite),
          matching: find.byType(AnimatedSwitcher)));
      expect(switcher.duration,
          reduceMotion ? Duration.zero : const Duration(milliseconds: 160));
      repository.like.completeError(const MobileRepositoryException('点赞失败'));
      await tester.pumpAndSettle();
      expect(find.text('赞'), findsOneWidget);
      expect(find.byIcon(Icons.favorite_border), findsOneWidget);
      expect(find.text('点赞失败'), findsOneWidget);
    });
  }

  testWidgets('comment failure retains draft and retry sends only once',
      (tester) async {
    final repository = _CircleRepository();
    await _show(tester, repository, reduceMotion: true);
    await tester.tap(find.text('评论'));
    await tester.pumpAndSettle();
    expect(find.byType(AnimatedSize), findsNothing);
    await tester.enterText(find.byType(TextField), '请继续跟进');
    await tester.tap(find.text('发送'));
    await tester.pumpAndSettle();
    expect(find.text('发送中…'), findsOneWidget);
    expect(tester.widget<TextField>(find.byType(TextField)).readOnly, isTrue);
    await tester.tap(find.text('发送中…'));
    expect(repository.comments, 1);
    repository.comment.completeError(const MobileRepositoryException('评论失败'));
    await tester.pumpAndSettle();
    expect(find.text('请继续跟进'), findsOneWidget);
    expect(find.text('评论失败'), findsOneWidget);
    repository.comment = Completer<void>();
    await tester.tap(find.text('发送'));
    await tester.pump();
    expect(repository.comments, 2);
    repository.comment.complete();
    await tester.pumpAndSettle();
    expect(find.byType(TextField), findsNothing);
    expect(find.text('我：请继续跟进'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
