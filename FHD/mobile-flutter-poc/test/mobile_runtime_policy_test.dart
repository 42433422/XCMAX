import 'package:flutter_test/flutter_test.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_api.dart';
import 'package:xcagi_flutter_poc/src/api/mobile_models.dart';
import 'package:xcagi_flutter_poc/src/policy/mobile_runtime_policy.dart';

void main() {
  setUp(MobileProductSkuConfig.resetRemoteSku);

  test('AuthRoutingPolicy routes enterprise sessions consistently', () {
    expect(
      MobileAuthRoutingPolicy.shouldUseEnterpriseAuthHost(
        isEnterprise: true,
        configuredHost: '192.168.1.8:17500',
      ),
      isTrue,
    );
    expect(
      MobileAuthRoutingPolicy.shouldUseEnterpriseAuthHost(
        isEnterprise: false,
        configuredHost: '192.168.1.8:17500',
      ),
      isFalse,
    );
    expect(
      MobileAuthRoutingPolicy.shouldUseEnterpriseAuthHost(
        isEnterprise: true,
        configuredHost: '   ',
      ),
      isFalse,
    );
    expect(
      MobileAuthRoutingPolicy.preferredServerModeAfterLogin(
        isEnterprise: true,
        configuredHost: '192.168.1.8:17500',
      ),
      'lan',
    );
    expect(
      MobileAuthRoutingPolicy.preferredServerModeAfterLogin(
        isEnterprise: true,
        configuredHost: '192.168.1.8:17500',
        currentMode: ' CLOUD ',
      ),
      'cloud',
    );
    expect(
      MobileAuthRoutingPolicy.preferredServerModeAfterLogin(
        isEnterprise: false,
        configuredHost: '192.168.1.8:17500',
      ),
      'cloud',
    );
  });

  test('ProductSkuConfig applies the remote SKU override', () {
    expect(
      MobileProductSkuConfig.effectiveSku(
        buildSku: MobileBuildConfig.productSku,
      ),
      'enterprise',
    );
    expect(
      MobileProductSkuConfig.isEnterprise(
        buildSku: MobileBuildConfig.productSku,
      ),
      isTrue,
    );
    expect(
      MobileProductSkuConfig.showsEnterpriseNav(
        buildSku: MobileBuildConfig.productSku,
      ),
      isTrue,
    );
    expect(
      MobileProductSkuConfig.accountKind(
        buildSku: MobileBuildConfig.productSku,
      ),
      'enterprise',
    );
    expect(
      MobileProductSkuConfig.displayEditionLabel(
        buildSku: MobileBuildConfig.productSku,
      ),
      '标准版',
    );

    MobileProductSkuConfig.setRemoteSku(' personal ');
    expect(MobileProductSkuConfig.remoteSku, 'personal');
    expect(
      MobileProductSkuConfig.effectiveSku(
        buildSku: MobileBuildConfig.productSku,
      ),
      'personal',
    );
    expect(
      MobileProductSkuConfig.isPersonal(buildSku: MobileBuildConfig.productSku),
      isTrue,
    );
    expect(
      MobileProductSkuConfig.showsEnterpriseNav(
        buildSku: MobileBuildConfig.productSku,
      ),
      isFalse,
    );
    expect(
      MobileProductSkuConfig.accountKind(
        buildSku: MobileBuildConfig.productSku,
      ),
      'personal',
    );
    expect(
      MobileProductSkuConfig.displayEditionLabel(
        buildSku: MobileBuildConfig.productSku,
      ),
      '个人版',
    );
  });

  test('Conversation runtime applies the enterprise and admin rules', () {
    final personal = MobileConversationRuntimePolicy.resolve(
      accountKind: 'personal',
      buildSku: 'personal',
    );
    expect(personal.adminMode, isFalse);
    expect(personal.enterpriseMode, isFalse);
    expect(personal.showPinnedSuperEmployees, isFalse);
    expect(personal.showCustomerService, isFalse);

    final enterprise = MobileConversationRuntimePolicy.resolve(
      accountKind: 'enterprise',
      buildSku: 'enterprise',
    );
    expect(enterprise.adminMode, isFalse);
    expect(enterprise.enterpriseMode, isTrue);
    expect(enterprise.showPinnedSuperEmployees, isTrue);
    expect(enterprise.showCustomerService, isTrue);

    final admin = MobileConversationRuntimePolicy.resolve(
      accountKind: ' admin_portal ',
      buildSku: 'personal',
    );
    expect(admin.adminMode, isTrue);
    expect(admin.enterpriseMode, isTrue);
    expect(admin.showPinnedSuperEmployees, isTrue);
    expect(admin.showCustomerService, isFalse);
  });

  test('MobileAppConfigData parses the cross-platform sku field', () {
    final config = MobileAppConfigData.fromJson({
      'ok': true,
      'legal_version': '2',
      'sku': 'personal',
      'profile_page': {'enabled': true},
    });

    expect(config.ok, isTrue);
    expect(config.legalVersion, '2');
    expect(config.sku, 'personal');
    expect(config.profilePage.enabled, isTrue);
  });
}
