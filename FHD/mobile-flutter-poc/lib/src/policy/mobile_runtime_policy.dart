class MobileAuthRoutingPolicy {
  const MobileAuthRoutingPolicy._();

  static bool shouldUseEnterpriseAuthHost({
    required bool isEnterprise,
    required String configuredHost,
  }) {
    return isEnterprise && configuredHost.trim().isNotEmpty;
  }

  static String preferredServerModeAfterLogin({
    required bool isEnterprise,
    required String configuredHost,
    String currentMode = '',
  }) {
    if (isEnterprise && currentMode.trim().toLowerCase() == 'cloud') {
      return 'cloud';
    }
    return shouldUseEnterpriseAuthHost(
      isEnterprise: isEnterprise,
      configuredHost: configuredHost,
    )
        ? 'lan'
        : 'cloud';
  }
}

class MobileProductSkuConfig {
  const MobileProductSkuConfig._();

  static String _remoteSku = '';

  static String get remoteSku => _remoteSku;

  static void setRemoteSku(String sku) {
    _remoteSku = sku.trim().toLowerCase();
  }

  static void resetRemoteSku() {
    _remoteSku = '';
  }

  static String effectiveSku({required String buildSku, String? remoteSku}) {
    final remote = (remoteSku ?? _remoteSku).trim().toLowerCase();
    if (remote.isNotEmpty) return remote;
    return buildSku.trim().toLowerCase();
  }

  static bool isEnterprise({required String buildSku, String? remoteSku}) {
    return effectiveSku(buildSku: buildSku, remoteSku: remoteSku) ==
        'enterprise';
  }

  static bool isPersonal({required String buildSku, String? remoteSku}) {
    return effectiveSku(buildSku: buildSku, remoteSku: remoteSku) == 'personal';
  }

  static bool showsEnterpriseNav({
    required String buildSku,
    String? remoteSku,
  }) {
    return isEnterprise(buildSku: buildSku, remoteSku: remoteSku);
  }

  static String accountKind({required String buildSku, String? remoteSku}) {
    return isEnterprise(buildSku: buildSku, remoteSku: remoteSku)
        ? 'enterprise'
        : 'personal';
  }

  static String displayEditionLabel({
    required String buildSku,
    String? remoteSku,
  }) {
    return isEnterprise(buildSku: buildSku, remoteSku: remoteSku)
        ? '标准版'
        : '个人版';
  }
}

class MobileConversationRuntime {
  const MobileConversationRuntime({
    required this.adminMode,
    required this.enterpriseMode,
  });

  final bool adminMode;
  final bool enterpriseMode;

  bool get showPinnedSuperEmployees => enterpriseMode || adminMode;

  bool get showCustomerService => enterpriseMode && !adminMode;
}

class MobileConversationRuntimePolicy {
  const MobileConversationRuntimePolicy._();

  static bool isAdminAccountKind(String accountKind) {
    return const {
      'admin',
      'admin_portal',
    }.contains(accountKind.trim().toLowerCase());
  }

  static MobileConversationRuntime resolve({
    required String accountKind,
    required String buildSku,
  }) {
    final adminMode = isAdminAccountKind(accountKind);
    return MobileConversationRuntime(
      adminMode: adminMode,
      enterpriseMode:
          MobileProductSkuConfig.showsEnterpriseNav(buildSku: buildSku) ||
              adminMode,
    );
  }
}
