import 'package:animations/animations.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:xcagi_flutter_poc/src/features/shell/home_shell.dart';
import 'package:xcagi_flutter_poc/src/theme/app_theme.dart';

void main() {
  test('home shell exposes the stable Flutter navigation contract', () {
    expect(flutterHomeShellBottomNavItemsForTest(), [
      {'route': 'chat', 'label': '消息'},
      {'route': 'work', 'label': 'AI员工'},
      {'route': 'discover', 'label': '工作台'},
      {'route': 'profile', 'label': '我'},
    ]);
  });

  testWidgets('tab transitions retain state and mute hidden page tickers',
      (tester) async {
    final first = GlobalKey<_TabProbeState>();
    final second = GlobalKey<_TabProbeState>();
    final pages = [_TabProbe(key: first), _TabProbe(key: second)];
    Widget shell(int index) => MaterialApp(
          home: HomeTabView(index: index, children: pages),
        );

    await tester.pumpWidget(shell(0));
    await tester.tap(find.text('Count 0'));
    await tester.pump();
    final firstState = first.currentState;
    final secondState = second.currentState;
    await tester.pumpWidget(shell(1));
    expect(first.currentState, same(firstState));
    expect(second.currentState, same(secondState));
    expect(TickerMode.valuesOf(first.currentContext!).enabled, isFalse);
    expect(TickerMode.valuesOf(second.currentContext!).enabled, isTrue);
    expect(
        tester
            .widget<FadeThroughTransition>(find.byType(FadeThroughTransition))
            .animation
            .value,
        lessThan(1));

    // A second selection during the first transition must not create another page.
    await tester.pumpWidget(shell(0));
    await tester.pumpAndSettle();
    expect(first.currentState, same(firstState));
    expect(find.text('Count 1'), findsOneWidget);
    expect(find.byType(_TabProbe, skipOffstage: false), findsNWidgets(2));
    expect(TickerMode.valuesOf(second.currentContext!).enabled, isFalse);
  });

  for (final accessibleNavigation in [false, true]) {
    testWidgets(
        'reduced motion switches immediately (accessibility: $accessibleNavigation)',
        (tester) async {
      Widget shell(int index) => MaterialApp(
            theme: AppTheme.light(),
            home: MediaQuery(
              data: MediaQueryData(
                disableAnimations: !accessibleNavigation,
                accessibleNavigation: accessibleNavigation,
              ),
              child: Scaffold(
                body: HomeTabView(
                    index: index,
                    children: const [Text('First'), Text('Second')]),
                bottomNavigationBar:
                    WeBottomNavBar(currentIndex: index, onSelect: (_) {}),
              ),
            ),
          );
      await tester.pumpWidget(shell(0));
      await tester.pumpWidget(shell(1));
      expect(find.text('Second'), findsOneWidget);
      final transition = tester
          .widget<FadeThroughTransition>(find.byType(FadeThroughTransition));
      expect(transition.animation.value, 1);
      expect(transition.animation.status, AnimationStatus.completed);
      expect(
          tester.widget<Text>(find.text('AI员工')).style?.color, AppTheme.brand);
      expect(
          tester
              .widget<IgnorePointer>(find
                  .ancestor(
                      of: find.byType(FadeThroughTransition),
                      matching: find.byType(IgnorePointer))
                  .first)
              .ignoring,
          isFalse);
    });
  }

  testWidgets('replacing account content keeps no outgoing page copy',
      (tester) async {
    Widget shell(String account, int index) => MaterialApp(
          home: HomeTabView(
            key: ValueKey(account),
            index: index,
            children: [Text('$account first'), Text('$account second')],
          ),
        );
    await tester.pumpWidget(shell('previous', 0));
    await tester.pumpWidget(shell('previous', 1));
    await tester.pumpWidget(shell('current', 0));
    expect(find.textContaining('previous', skipOffstage: false), findsNothing);
    expect(find.text('current first'), findsOneWidget);
    expect(find.byType(IndexedStack), findsOneWidget);
  });
}

class _TabProbe extends StatefulWidget {
  const _TabProbe({super.key});

  @override
  State<_TabProbe> createState() => _TabProbeState();
}

class _TabProbeState extends State<_TabProbe> {
  var count = 0;

  @override
  Widget build(BuildContext context) => TextButton(
        onPressed: () => setState(() => count++),
        child: Text('Count $count'),
      );
}
