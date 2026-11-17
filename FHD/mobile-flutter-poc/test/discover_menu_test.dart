import 'package:flutter_test/flutter_test.dart';
import 'package:xcagi_flutter_poc/src/features/discover/discover_screen.dart';

void main() {
  test('inventory ledger retains web route while materials stays native', () {
    expect(nativeMaterialsModForPath('/materials'), '');
    expect(nativeMaterialsModForPath('/mod/erp/materials'), 'erp');
    for (final path in [
      '/inventory',
      '/mod/erp/inventory',
      '/mod/erp/inventory?warehouse=2',
      'https://other/materials'
    ]) {
      expect(nativeMaterialsModForPath(path), isNull, reason: path);
    }
  });
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
