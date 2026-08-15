package com.modstore.service;

import java.math.BigDecimal;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;

/** Canonical separation between XCAGI account licenses and VIP/SVIP usage memberships. */
public final class AccountLicensePlans {
    public record Metadata(
            String id,
            String name,
            BigDecimal price,
            String licenseType,
            Integer durationDays,
            String accountTier,
            String badge,
            int quotaCents,
            String description,
            List<String> features) {}

    public static final List<Metadata> PLANS = List.of(
            new Metadata("saas-trial-30", "30 天试用", new BigDecimal("99.00"), "trial", 30,
                    "normal", "试用", 10000,
                    "99 元体验账户，含 100 元额度，30 天到期后冻结，可购买永久授权继续使用。",
                    List.of("XCAGI 桌面端账号授权", "30 天全功能体验", "含 100 元 AI 额度")),
            new Metadata("saas-permanent-starter", "永久授权 · 1–5 万", new BigDecimal("49999.00"),
                    "permanent", null, "normal", "永久", 0,
                    "1 个行业 Mod 定制 + 四部门 AI 员工配置 + 1-3 天上线交付 + 1 年免费维护。",
                    List.of("XCAGI 永久账号授权", "1 个行业 Mod 定制", "1 年免费维护")),
            new Metadata("saas-permanent-growth", "永久授权 · 5–10 万", new BigDecimal("99999.00"),
                    "permanent", null, "pro", "永久", 0,
                    "多行业 Mod 组合 + 现有系统对接 + 专属 AI 员工训练 + 2 年免费维护。",
                    List.of("XCAGI 永久账号授权", "多行业 Mod 与系统对接", "2 年免费维护")),
            new Metadata("saas-permanent-max", "永久授权 · 10–50 万", new BigDecimal("499999.00"),
                    "permanent", null, "max", "永久", 0,
                    "集团多组织架构 + 3 年免费维护，一次购买永久使用。",
                    List.of("XCAGI 永久账号授权", "集团多组织架构", "3 年免费维护")),
            new Metadata("saas-permanent-ultra", "永久授权 · 50–100 万", new BigDecimal("999999.00"),
                    "permanent", null, "ultra", "永久", 0,
                    "源码托管 + 二开授权 + SLA 99.9% 保障，一次购买永久使用。",
                    List.of("XCAGI 永久账号授权", "源码托管与二开授权", "SLA 99.9% 保障"))
    );

    private static final Map<String, Metadata> BY_ID = PLANS.stream()
            .collect(java.util.stream.Collectors.toUnmodifiableMap(Metadata::id, value -> value));
    public static final Set<String> IDS = BY_ID.keySet();

    private AccountLicensePlans() {}

    public static boolean isAccountLicense(String planId) {
        return planId != null && IDS.contains(planId.trim());
    }

    public static Optional<Metadata> find(String planId) {
        return Optional.ofNullable(planId == null ? null : BY_ID.get(planId.trim()));
    }
}
