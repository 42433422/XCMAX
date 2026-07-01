import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:xcagi_flutter_poc/src/features/discover/discover_screen.dart';

void main() {
  test('Discover desktop menu policy mirrors Android source tables', () {
    expect(
      flutterDiscoverHiddenKeysForTest(),
      _androidDiscoverHiddenKeys(),
      reason: 'Flutter must hide the same desktop menu keys as Android.',
    );
    expect(
      flutterDiscoverNativeRouteMapForTest(),
      _androidDiscoverNativeRouteMap(),
      reason: 'Flutter native route dispatch must mirror Android.',
    );
  });
}

Map<String, String> _androidDiscoverNativeRouteMap() {
  final routes = _androidRoutes();
  final source = _androidDiscoverSource();
  final matches = RegExp(
    r'"([^"]+)"\s+to\s+Routes\.([A-Z0-9_]+)',
  ).allMatches(source);
  return {
    for (final match in matches)
      match.group(1)!: routes[match.group(2)!] ??
          (throw StateError('Unknown Android route ${match.group(2)}')),
  };
}

Set<String> _androidDiscoverHiddenKeys() {
  final source = _androidDiscoverSource();
  final match = RegExp(
    r'HIDDEN_KEYS:[\s\S]*?setOf\(([\s\S]*?)\)',
  ).firstMatch(source);
  if (match == null) {
    throw StateError('Android DiscoverScreen.kt HIDDEN_KEYS not found');
  }
  return RegExp(
    r'"([^"]+)"',
  ).allMatches(match.group(1)!).map((match) => match.group(1)!).toSet();
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

String _androidDiscoverSource() {
  return File(
    '../mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/navigation/DiscoverScreen.kt',
  ).readAsStringSync();
}
