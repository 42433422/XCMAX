import 'package:flutter_test/flutter_test.dart';
import 'package:xcagi_flutter_poc/src/policy/mobile_sync_policy.dart';

void main() {
  test('MobileSyncPolicy recognizes the published admin account kinds', () {
    for (final kind in {'admin', 'admin_portal'}) {
      expect(
        MobileSyncPolicy.isAdminAccountKind(kind),
        isTrue,
        reason: 'Flutter must treat $kind as an admin account.',
      );
      expect(
        MobileSyncPolicy.isAdminAccountKind(' $kind '.toUpperCase()),
        isTrue,
      );
    }

    expect(MobileSyncPolicy.isAdminAccountKind('enterprise'), isFalse);
    expect(MobileSyncPolicy.isAdminAccountKind('personal'), isFalse);
  });

  test('MobileSyncPolicy auto-sync skip follows the mobile contract', () {
    expect(MobileSyncPolicy.shouldSkipAutoSync(host: '', mode: ''), isTrue);
    expect(
      MobileSyncPolicy.shouldSkipAutoSync(host: '   ', mode: 'lan'),
      isTrue,
    );
    expect(
      MobileSyncPolicy.shouldSkipAutoSync(host: '', mode: 'cloud'),
      isFalse,
    );
    expect(
      MobileSyncPolicy.shouldSkipAutoSync(
        host: '192.168.1.8:17500',
        mode: 'lan',
      ),
      isFalse,
    );
  });

  test(
    'MobileSyncPolicy refreshes the employee roster for privileged accounts',
    () {
      expect(
        MobileSyncPolicy.shouldRefreshEmployeeRoster(
          accountKind: 'enterprise',
          showsEnterpriseNav: true,
        ),
        isTrue,
      );
      expect(
        MobileSyncPolicy.shouldRefreshEmployeeRoster(
          accountKind: 'admin',
          showsEnterpriseNav: false,
        ),
        isTrue,
      );
      expect(
        MobileSyncPolicy.shouldRefreshEmployeeRoster(
          accountKind: 'admin_portal',
          showsEnterpriseNav: false,
        ),
        isTrue,
      );
      expect(
        MobileSyncPolicy.shouldRefreshEmployeeRoster(
          accountKind: 'personal',
          showsEnterpriseNav: false,
        ),
        isFalse,
      );
    },
  );

  test('MobileSyncPolicy status labels remain stable', () {
    expect(
      MobileSyncPolicy.statusLabel(
        lastSyncAt: '',
        mode: 'cloud',
        pcOnline: false,
      ),
      '尚未同步',
    );
    expect(
      MobileSyncPolicy.statusLabel(
        lastSyncAt: '2026-07-01T19:20:30.123Z',
        mode: 'cloud',
        pcOnline: false,
      ),
      '云端同步 2026-07-01 19:20:30',
    );
    expect(
      MobileSyncPolicy.statusLabel(
        lastSyncAt: '2026-07-01T19:20:30.123Z',
        mode: 'lan',
        pcOnline: false,
      ),
      '桌面执行端未连接',
    );
    expect(
      MobileSyncPolicy.statusLabel(
        lastSyncAt: '2026-07-01T19:20:30.123Z',
        mode: 'lan',
        pcOnline: true,
      ),
      '上次同步 2026-07-01 19:20:30',
    );
  });
}
