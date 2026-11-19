import 'package:flutter_test/flutter_test.dart';
import 'package:xcagi_flutter_poc/src/features/discover/discover_screen.dart';

void main() {
  test('inventory ledger and materials have distinct scoped native routes', () {
    expect(nativeMaterialsModForPath('/materials'), '');
    expect(nativeInventoryModForPath('/inventory'), '');
    expect(nativeInventoryModForPath('/mod/xcagi-erp-domain-bridge/inventory'),
        'xcagi-erp-domain-bridge');
    expect(nativeInventoryModForPath('/mod/erp/inventory'), isNull);
    expect(nativeInventoryModForPath('/inventory?warehouse=2'), isNull);
    expect(nativeInventoryModForPath('https://other/inventory'), isNull);
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
