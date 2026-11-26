package com.modstore.service;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.IOException;
import java.io.InputStream;
import java.math.BigDecimal;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.stream.Stream;

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

    public static final String PERSONAL_PLAN_ID = "saas-personal-free";
    public static final String STANDARD_PLAN_ID = "saas-permanent-standard";
    public static final List<Metadata> PLANS = List.of(
            new Metadata(PERSONAL_PLAN_ID, "个人使用版", BigDecimal.ZERO, "free", null,
                    "normal", "免费", 500, "免费使用 XCAGI 桌面端基础功能，不含任何 Mod。",
                    List.of("桌面端基础功能", "验证邮箱且活动预算可用时可领取 5 元 AI 额度", "无 Mod 权益")),
            new Metadata("saas-trial-30", "30 天全功能体验", new BigDecimal("99.00"), "trial", 30,
                    "normal", "体验", 10000,
                    "用 30 天完整体验 XCAGI，包含 100 元 AI 使用额度。",
                    List.of("XCAGI 桌面端完整功能", "30 天使用期", "100 元 AI 使用额度")),
            new Metadata(STANDARD_PLAN_ID, "XCAGI 软件买断", new BigDecimal("3000.00"),
                    "permanent", null, "normal", "一次购买", 0,
                    "3,000 元一次购买，永久使用已购软件；定制按确认的报价收费，AI 调用按量另计。",
                    List.of("软件永久使用", "无软件续租费", "定制另行报价", "AI 调用按量付费"))
    );
    // Historical grants and pending orders keep their original product identity.
    public static final List<Metadata> LEGACY_PLANS = List.of(
            new Metadata("saas-permanent-starter", "企业启航版", new BigDecimal("49999.00"),
                    "permanent", null, "normal", "永久使用", 0,
                    "适合首次部署 XCAGI 的企业，包含 1 个行业 Mod、四部门 AI 员工配置、上线交付与 1 年维护。",
                    List.of("永久使用 XCAGI", "1 个行业 Mod", "四部门 AI 员工配置", "1 年维护")),
            new Metadata("saas-permanent-growth", "企业成长版", new BigDecimal("99999.00"),
                    "permanent", null, "pro", "永久使用", 0,
                    "适合需要多业务协同或现有系统对接的企业，包含专属 AI 员工训练与 2 年维护。",
                    List.of("永久使用 XCAGI", "多行业 Mod 组合", "现有系统对接", "专属 AI 员工训练", "2 年维护")),
            new Metadata("saas-permanent-max", "集团协同版", new BigDecimal("499999.00"),
                    "permanent", null, "max", "永久使用", 0,
                    "适合多组织、多分支机构协同的集团企业，包含集团架构支持与 3 年维护。",
                    List.of("永久使用 XCAGI", "集团多组织架构", "多分支协同", "3 年维护")),
            new Metadata("saas-permanent-ultra", "企业旗舰版", new BigDecimal("999999.00"),
                    "permanent", null, "ultra", "永久使用", 0,
                    "适合需要深度定制与长期技术保障的企业，包含源码托管、二次开发授权与 99.9% SLA。",
                    List.of("永久使用 XCAGI", "源码托管", "二次开发授权", "99.9% SLA"))
    );

    private static final Map<String, Metadata> BY_ID = Stream.concat(PLANS.stream(), LEGACY_PLANS.stream())
            .collect(java.util.stream.Collectors.toUnmodifiableMap(Metadata::id, value -> value));
    public static final Set<String> IDS = BY_ID.keySet();

    private AccountLicensePlans() {}

    public static boolean isAccountLicense(String planId) {
        return planId != null && IDS.contains(planId.trim());
    }

    public static boolean isLegacy(String planId) {
        return planId != null && LEGACY_PLANS.stream().anyMatch(plan -> plan.id().equals(planId.trim()));
    }

    public static boolean isPermanent(String planId) {
        return find(planId).map(plan -> "permanent".equals(plan.licenseType())).orElse(false);
    }

    public static Optional<Metadata> find(String planId) {
        return Optional.ofNullable(planId == null ? null : BY_ID.get(planId.trim()));
    }

    public static Map<String, Object> commercialTerms() {
        try (InputStream resource = AccountLicensePlans.class.getResourceAsStream("/commerce_terms.generated.json")) {
            return resource == null ? Map.of() : new ObjectMapper().readValue(resource, new TypeReference<>() {});
        } catch (IOException exception) {
            throw new IllegalStateException("Invalid packaged commercial terms", exception);
        }
    }
}
