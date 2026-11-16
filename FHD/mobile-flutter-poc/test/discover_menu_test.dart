import 'package:flutter_test/flutter_test.dart';
import 'package:xcagi_flutter_poc/src/features/discover/discover_screen.dart';

void main() {
  test('workbench keeps community and native actions outside account settings',
      () {
    expect(flutterDiscoverHiddenKeysForTest(),
        {'chat', 'im', 'settings', 'admin-entitlements'});
    expect(flutterDiscoverNativeRouteMapForTest(), {
      'ai-circle': 'circle',
      'employee-workflow': 'employee_workspace',
      'workflow-employee-space': 'employee_workspace',
      'tasks': 'tasks',
      'approval-hub': 'approval',
      'photo-files': 'assistant_attachments',
      'pair-desktop': 'scan',
    });
    expect(flutterDiscoverNativeRouteMapForTest(),
        isNot(contains('ai-ecosystem')));
  });
}
