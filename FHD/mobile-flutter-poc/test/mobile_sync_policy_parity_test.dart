import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:xcagi_flutter_poc/src/policy/mobile_sync_policy.dart';

void main() {
  test('MobileSyncPolicy admin account kinds mirror Android source', () {
    final androidAdminKinds = _androidAdminAccountKinds();

    for (final kind in androidAdminKinds) {
      expect(
        MobileSyncPolicy.isAdminAccountKind(kind),
        isTrue,
        reason: 'Flutter must treat Android admin account kind $kind as admin.',
      );
      expect(
          MobileSyncPolicy.isAdminAccountKind(' $kind '.toUpperCase()), isTrue);
    }

    expect(MobileSyncPolicy.isAdminAccountKind('enterprise'), isFalse);
    expect(MobileSyncPolicy.isAdminAccountKind('personal'), isFalse);
  });

  test('MobileSyncPolicy auto-sync skip mirrors Android worker policy', () {
    expect(
      MobileSyncPolicy.shouldSkipAutoSync(host: '', mode: ''),
      isTrue,
    );
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
          host: '192.168.1.8:17500', mode: 'lan'),
      isFalse,
    );
  });

  test('MobileSyncPolicy employee roster refresh mirrors Android source', () {
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
  });

  test('MobileSyncPolicy status labels mirror Android wording', () {
    final labels = _androidStatusLabels();
    expect(labels, containsAll(['尚未同步', '云端同步', '桌面执行端未连接', '上次同步']));

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

Set<String> _androidAdminAccountKinds() {
  final source = _androidMobileSyncSource();
  final match = RegExp(
    r'isAdminAccountKind[\s\S]*?setOf\(([^)]*)\)',
  ).firstMatch(source);
  if (match == null) {
    throw StateError('Android MobileSyncPolicy admin set not found');
  }
  return RegExp(
    r'"([^"]+)"',
  ).allMatches(match.group(1)!).map((match) => match.group(1)!).toSet();
}

Set<String> _androidStatusLabels() {
  final source = _androidMobileSyncSource();
  final block = RegExp(
    r'fun statusLabel\([\s\S]*?\n    }\n}',
  ).firstMatch(source);
  if (block == null) {
    throw StateError('Android MobileSyncPolicy statusLabel block not found');
  }
  return RegExp(
    r'"([^"$]+)(?:\s+\$\{[^}]+})?"',
  ).allMatches(block.group(0)!).map((match) => match.group(1)!).toSet();
}

String _androidMobileSyncSource() {
  return File(
    '../mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/core/sync/MobileSyncRepository.kt',
  ).readAsStringSync();
}
