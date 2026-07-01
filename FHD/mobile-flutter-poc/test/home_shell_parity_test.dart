import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:xcagi_flutter_poc/src/features/shell/home_shell.dart';

void main() {
  test('Home shell bottom nav mirrors Android nav host table', () {
    expect(
      flutterHomeShellBottomNavItemsForTest(),
      _androidBottomNavItems(),
      reason:
          'Flutter bottom nav order, routes, and labels must match Android.',
    );
  });
}

List<Map<String, String>> _androidBottomNavItems() {
  final routes = _androidRoutes();
  final source = File(
    '../mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/navigation/XcagiNavHost.kt',
  ).readAsStringSync();
  return RegExp(
    r'WeBottomNavItem\(\s*Routes\.([A-Z0-9_]+),\s*"([^"]+)"',
  ).allMatches(source).map((match) {
    final routeName = match.group(1)!;
    return {
      'route': routes[routeName] ??
          (throw StateError('Unknown Android route $routeName')),
      'label': match.group(2)!,
    };
  }).toList(growable: false);
}

Map<String, String> _androidRoutes() {
  final source = File(
    '../mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/navigation/Routes.kt',
  ).readAsStringSync();
  return {
    for (final match in RegExp(
      r'const val ([A-Z0-9_]+) = "([^"]+)"',
    ).allMatches(source))
      match.group(1)!: match.group(2)!,
  };
}
