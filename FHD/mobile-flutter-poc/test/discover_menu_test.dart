import 'package:flutter_test/flutter_test.dart';
import 'package:xcagi_flutter_poc/src/features/discover/discover_screen.dart';

void main() {
  test('discover menu exposes the stable Flutter route contract', () {
    expect(flutterDiscoverHiddenKeysForTest(), {'chat', 'im'});
    expect(flutterDiscoverNativeRouteMapForTest(), {
      'chat': 'ai_chat',
      'im': 'im',
      'ai-ecosystem': 'ai_employees',
      'employee-workflow': 'work',
      'settings': 'settings',
    });
  });
}
