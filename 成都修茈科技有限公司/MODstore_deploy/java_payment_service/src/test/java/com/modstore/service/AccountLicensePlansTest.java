package com.modstore.service;

import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.util.Map;
import java.util.stream.Collectors;

import static org.assertj.core.api.Assertions.assertThat;

class AccountLicensePlansTest {

    @Test
    void publicCatalogHasOneBuyoutAndPreservesTrialAndHistoricalMetadata() {
        Map<String, String> expectedNames = Map.of(
                "saas-personal-free", "个人使用版",
                "saas-trial-30", "30 天全功能体验",
                "saas-permanent-standard", "XCAGI 软件买断");
        Map<String, BigDecimal> expectedPrices = Map.of(
                "saas-personal-free", BigDecimal.ZERO,
                "saas-trial-30", new BigDecimal("99.00"),
                "saas-permanent-standard", new BigDecimal("3000.00"));

        assertThat(AccountLicensePlans.PLANS.stream()
                .collect(Collectors.toMap(AccountLicensePlans.Metadata::id, AccountLicensePlans.Metadata::name)))
                .isEqualTo(expectedNames);
        assertThat(AccountLicensePlans.PLANS.stream()
                .collect(Collectors.toMap(AccountLicensePlans.Metadata::id, AccountLicensePlans.Metadata::price)))
                .isEqualTo(expectedPrices);

        assertThat(AccountLicensePlans.find("saas-personal-free").orElseThrow().quotaCents())
                .isEqualTo(500);
        assertThat(AccountLicensePlans.find("saas-trial-30").orElseThrow().durationDays()).isEqualTo(30);
        assertThat(AccountLicensePlans.find("saas-trial-30").orElseThrow().quotaCents()).isEqualTo(10000);
        assertThat(AccountLicensePlans.find("saas-permanent-growth").orElseThrow().price())
                .isEqualByComparingTo("99999.00");
        assertThat(AccountLicensePlans.find("saas-permanent-ultra").orElseThrow().accountTier())
                .isEqualTo("ultra");
        assertThat(AccountLicensePlans.IDS).contains("saas-permanent-starter", "saas-permanent-growth",
                "saas-permanent-max", "saas-permanent-ultra");

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
