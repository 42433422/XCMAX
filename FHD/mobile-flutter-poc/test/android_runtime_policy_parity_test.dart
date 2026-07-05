import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_api.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_models.dart';
import 'package:xcagi_flutter_poc/src/policy/android_runtime_policy.dart';

void main() {
  setUp(AndroidProductSkuConfig.resetRemoteSku);

  test('AuthRoutingPolicy mirrors Android source and behavior', () {
    final source = _androidAuthRoutingPolicySource();
    expect(source, contains('isEnterprise && configuredHost.isNotBlank()'));
    expect(source, contains('currentMode.trim().lowercase() == "cloud"'));
    expect(source, contains('ServerMode.LAN'));
    expect(source, contains('ServerMode.CLOUD'));

    expect(
      AndroidAuthRoutingPolicy.shouldUseEnterpriseAuthHost(
        isEnterprise: true,
        configuredHost: '192.168.1.8:17500',
      ),
      isTrue,
    );
    expect(
      AndroidAuthRoutingPolicy.shouldUseEnterpriseAuthHost(
        isEnterprise: false,
        configuredHost: '192.168.1.8:17500',
      ),
      isFalse,
    );
    expect(
      AndroidAuthRoutingPolicy.shouldUseEnterpriseAuthHost(
        isEnterprise: true,
        configuredHost: '   ',
      ),
      isFalse,
    );
    expect(
      AndroidAuthRoutingPolicy.preferredServerModeAfterLogin(
        isEnterprise: true,
        configuredHost: '192.168.1.8:17500',
      ),
      'lan',
    );
    expect(
      AndroidAuthRoutingPolicy.preferredServerModeAfterLogin(
        isEnterprise: true,
        configuredHost: '192.168.1.8:17500',
        currentMode: ' CLOUD ',
      ),
      'cloud',
    );
    expect(
      AndroidAuthRoutingPolicy.preferredServerModeAfterLogin(
        isEnterprise: false,
        configuredHost: '192.168.1.8:17500',
      ),
      'cloud',
    );
  });

  test('ProductSkuConfig mirrors Android runtime remote SKU override', () {
    final source = _androidProductSkuConfigSource();
    expect(source, contains('remoteSku.ifBlank { sku }'));
    expect(source, contains('get() = effectiveSku == "enterprise"'));
    expect(source, contains('get() = effectiveSku == "personal"'));
    expect(source, contains('get() = if (isEnterprise) "enterprise"'));
    expect(source, contains('get() = if (isEnterprise) "企业版"'));

    expect(
      AndroidProductSkuConfig.effectiveSku(
        buildSku: MobileAndroidBuild.productSku,
      ),
      'enterprise',
    );
    expect(
      AndroidProductSkuConfig.isEnterprise(
        buildSku: MobileAndroidBuild.productSku,
      ),
      isTrue,
    );
    expect(
      AndroidProductSkuConfig.showsEnterpriseNav(
        buildSku: MobileAndroidBuild.productSku,
      ),
      isTrue,
    );
    expect(
      AndroidProductSkuConfig.accountKind(
        buildSku: MobileAndroidBuild.productSku,
      ),
      'enterprise',
    );
    expect(
      AndroidProductSkuConfig.displayEditionLabel(
        buildSku: MobileAndroidBuild.productSku,
      ),
      '企业版',
    );

    AndroidProductSkuConfig.setRemoteSku(' personal ');
    expect(AndroidProductSkuConfig.remoteSku, 'personal');
    expect(
      AndroidProductSkuConfig.effectiveSku(
        buildSku: MobileAndroidBuild.productSku,
      ),
      'personal',
    );
    expect(
      AndroidProductSkuConfig.isPersonal(
        buildSku: MobileAndroidBuild.productSku,
      ),
      isTrue,
    );
    expect(
      AndroidProductSkuConfig.showsEnterpriseNav(
        buildSku: MobileAndroidBuild.productSku,
      ),
      isFalse,
    );
    expect(
      AndroidProductSkuConfig.accountKind(
        buildSku: MobileAndroidBuild.productSku,
      ),
      'personal',
    );
    expect(
      AndroidProductSkuConfig.displayEditionLabel(
        buildSku: MobileAndroidBuild.productSku,
      ),
      '个人版',
    );
  });

  test('Conversation runtime mirrors Android effective enterprise rule', () {
    final source = _androidAppViewModelSource();
    expect(
      source,
      contains('ProductSkuConfig.showsEnterpriseNav || isAdminAccountKind(it)'),
    );
    expect(
      source,
      contains(
        'val isEnterprise = ProductSkuConfig.showsEnterpriseNav || adminMode',
      ),
    );
    expect(
        source, contains('showCustomerService = isEnterprise && !adminMode'));

    final personal = AndroidConversationRuntimePolicy.resolve(
      accountKind: 'personal',
      buildSku: 'personal',
    );
    expect(personal.adminMode, isFalse);
    expect(personal.enterpriseMode, isFalse);
    expect(personal.showPinnedSuperEmployees, isFalse);
    expect(personal.showCustomerService, isFalse);

    final enterprise = AndroidConversationRuntimePolicy.resolve(
      accountKind: 'enterprise',
      buildSku: 'enterprise',
    );
    expect(enterprise.adminMode, isFalse);
    expect(enterprise.enterpriseMode, isTrue);
    expect(enterprise.showPinnedSuperEmployees, isTrue);
    expect(enterprise.showCustomerService, isTrue);

    final admin = AndroidConversationRuntimePolicy.resolve(
      accountKind: ' admin_portal ',
      buildSku: 'personal',
    );
    expect(admin.adminMode, isTrue);
    expect(admin.enterpriseMode, isTrue);
    expect(admin.showPinnedSuperEmployees, isTrue);
    expect(admin.showCustomerService, isFalse);
  });

  test('MobileAppConfigData parses Android sku field', () {
    final source = _androidAppConfigModelsSource();
    expect(source, contains('val sku: String = ""'));

    final config = MobileAppConfigData.fromJson({
      'ok': true,
      'legal_version': '2',
      'sku': 'personal',
      'profile_page': {
        'enabled': true,
      },
    });

    expect(config.ok, isTrue);
    expect(config.legalVersion, '2');
    expect(config.sku, 'personal');
    expect(config.profilePage.enabled, isTrue);
  });
}

String _androidAuthRoutingPolicySource() {
  final source = File(
    '../mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/core/repository/XcagiRepository.kt',
  ).readAsStringSync();
  final match = RegExp(
    r'internal object AuthRoutingPolicy[\s\S]*?\n}\n\n@Singleton',
  ).firstMatch(source);
  if (match == null) {
    throw StateError('Android AuthRoutingPolicy source not found');
  }
  return match.group(0)!;
}

String _androidProductSkuConfigSource() {
  return File(
    '../mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/core/ProductSkuConfig.kt',
  ).readAsStringSync();
}

String _androidAppConfigModelsSource() {
  return File(
    '../mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/core/model/AppConfigModels.kt',
  ).readAsStringSync();
}

String _androidAppViewModelSource() {
  return File(
    '../mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/ui/AppViewModel.kt',
  ).readAsStringSync();
}
