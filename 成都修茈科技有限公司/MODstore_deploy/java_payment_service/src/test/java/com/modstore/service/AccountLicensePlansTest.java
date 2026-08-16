package com.modstore.service;

import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.util.Map;
import java.util.stream.Collectors;

import static org.assertj.core.api.Assertions.assertThat;

class AccountLicensePlansTest {

    @Test
    void publicPlanCopyMatchesTheCustomerCatalogWithoutChangingPrices() {
        Map<String, String> expectedNames = Map.of(
                "saas-trial-30", "30 天全功能体验",
                "saas-permanent-starter", "企业启航版",
                "saas-permanent-growth", "企业成长版",
                "saas-permanent-max", "集团协同版",
                "saas-permanent-ultra", "企业旗舰版");
        Map<String, BigDecimal> expectedPrices = Map.of(
                "saas-trial-30", new BigDecimal("99.00"),
                "saas-permanent-starter", new BigDecimal("49999.00"),
                "saas-permanent-growth", new BigDecimal("99999.00"),
                "saas-permanent-max", new BigDecimal("499999.00"),
                "saas-permanent-ultra", new BigDecimal("999999.00"));

        assertThat(AccountLicensePlans.PLANS.stream()
                .collect(Collectors.toMap(AccountLicensePlans.Metadata::id, AccountLicensePlans.Metadata::name)))
                .isEqualTo(expectedNames);
        assertThat(AccountLicensePlans.PLANS.stream()
                .collect(Collectors.toMap(AccountLicensePlans.Metadata::id, AccountLicensePlans.Metadata::price)))
                .isEqualTo(expectedPrices);

        String publicCopy = AccountLicensePlans.PLANS.stream()
                .map(plan -> String.join(" ", plan.name(), plan.description(), plan.badge(),
                        String.join(" ", plan.features())))
                .collect(Collectors.joining(" "));
        assertThat(publicCopy)
                .doesNotContain("VIP / SVIP")
                .doesNotContain("不代替账号授权")
                .doesNotContain("桌面端账号授权")
                .doesNotContain("永久账号授权")
                .doesNotContain("永久授权 ·");
    }
}
