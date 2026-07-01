class MobileSyncPolicy {
  const MobileSyncPolicy._();

  static bool shouldSkipAutoSync({
    required String host,
    required String mode,
  }) {
    return host.trim().isEmpty && mode.trim().toLowerCase() != 'cloud';
  }

  static bool isAdminAccountKind(String accountKind) {
    return const {'admin', 'admin_portal'}
        .contains(accountKind.trim().toLowerCase());
  }

  static bool shouldRefreshEmployeeRoster({
    required String accountKind,
    required bool showsEnterpriseNav,
  }) {
    return showsEnterpriseNav || isAdminAccountKind(accountKind);
  }

  static String statusLabel({
    required String lastSyncAt,
    required String mode,
    required bool pcOnline,
  }) {
    final last = lastSyncAt.trim();
    final normalizedMode = mode.trim().toLowerCase();
    if (last.isEmpty) return '尚未同步';
    final displayTime = last.take(19).replaceAll('T', ' ');
    if (normalizedMode == 'cloud') return '云端同步 $displayTime';
    if (!pcOnline) return '桌面执行端未连接';
    return '上次同步 $displayTime';
  }
}

extension _MobileSyncStringTake on String {
  String take(int count) {
    if (length <= count) return this;
    return substring(0, count);
  }
}
