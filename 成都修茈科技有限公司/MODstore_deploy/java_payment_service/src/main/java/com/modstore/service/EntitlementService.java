package com.modstore.service;

import com.modstore.model.CatalogItem;
import com.modstore.model.Entitlement;
import com.modstore.model.PlanTemplate;
import com.modstore.model.Purchase;
import com.modstore.model.Quota;
import com.modstore.model.User;
import com.modstore.model.UserPlan;
import com.modstore.repository.CatalogItemRepository;
import com.modstore.repository.EntitlementRepository;
import com.modstore.repository.QuotaRepository;
import com.modstore.repository.UserPlanRepository;
import com.modstore.repository.UserRepository;
import com.modstore.repository.PurchaseRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.LocalDateTime;
import java.util.Comparator;
import java.util.HashMap;
import java.util.HexFormat;
import java.util.List;
import java.util.Map;
import java.util.Optional;

@Slf4j
@Service
@RequiredArgsConstructor
public class EntitlementService {
    
    private final PurchaseRepository purchaseRepository;
    private final EntitlementRepository entitlementRepository;
    private final UserPlanRepository userPlanRepository;
    private final UserRepository userRepository;
    private final QuotaRepository quotaRepository;
    private final CatalogItemRepository catalogItemRepository;
    private final ObjectMapper objectMapper = new ObjectMapper();
    
    @Transactional
    public void createPurchase(User user, Long catalogId, BigDecimal amount) {
        Purchase purchase = new Purchase();
        purchase.setUser(user);
        purchase.setCatalogId(catalogId);
        purchase.setAmount(amount);
        purchaseRepository.save(purchase);
        log.info("创建购买记录: userId={}, catalogId={}, amount={}", 
                user.getId(), catalogId, amount);
    }

    @Transactional
    public void grantCatalogEntitlement(User user, Long catalogId, String sourceOrderId) {
        if (entitlementRepository.findBySourceOrderId(sourceOrderId).isPresent()) {
            return;
        }
        String entType = "mod";
        CatalogItem item = catalogItemRepository.findById(catalogId).orElse(null);
        if (item != null && item.getArtifact() != null
                && "employee_pack".equalsIgnoreCase(item.getArtifact().trim())) {
            entType = "employee";
        }
        Entitlement entitlement = new Entitlement();
        entitlement.setUser(user);
        entitlement.setCatalogId(catalogId);
        entitlement.setEntitlementType(entType);
        entitlement.setSourceOrderId(sourceOrderId);
        entitlement.setMetadataJson("{\"source\":\"alipay\"}");
        entitlementRepository.save(entitlement);
        if ("employee".equals(entType)) {
            incrementEmployeeCountQuota(user);
        }
    }

    private void incrementEmployeeCountQuota(User user) {
        Quota quota = quotaRepository.findByUserAndQuotaType(user, "employee_count").orElseGet(() -> {
            Quota q = new Quota();
            q.setUser(user);
            q.setQuotaType("employee_count");
            q.setUsed(0);
            q.setTotal(0);
            return q;
        });
        quota.setTotal(quota.getTotal() + 1);
        quotaRepository.save(quota);
    }

    @Transactional
    public void activatePlan(User user, PlanTemplate plan, String sourceOrderId) {
        Optional<UserPlan> current = userPlanRepository.findFirstByUserAndActiveTrueOrderByStartedAtDesc(user);
        current.ifPresent(row -> {
            row.setActive(false);
            userPlanRepository.save(row);
        });

        UserPlan userPlan = new UserPlan();
        userPlan.setUser(user);
        userPlan.setPlan(plan);
        userPlan.setStartedAt(LocalDateTime.now());
        userPlan.setSourceOrderId(sourceOrderId);
        userPlan.setActive(true);
        userPlanRepository.save(userPlan);

        Entitlement entitlement = new Entitlement();
        entitlement.setUser(user);
        entitlement.setEntitlementType("plan");
        entitlement.setSourceOrderId(sourceOrderId);
        entitlement.setMetadataJson("{\"plan_id\":\"" + plan.getId() + "\"}");
        entitlementRepository.save(entitlement);

        user.setAccountState("active");
        userRepository.save(user);

        applyPlanQuotas(user, plan);
    }

    private void applyPlanQuotas(User user, PlanTemplate plan) {
        Map<String, Integer> quotas;
        try {
            quotas = objectMapper.readValue(plan.getQuotasJson() == null ? "{}" : plan.getQuotasJson(),
                    new TypeReference<Map<String, Integer>>() {});
        } catch (Exception e) {
            log.warn("套餐配额 JSON 解析失败: planId={}", plan.getId(), e);
            return;
        }
        for (Map.Entry<String, Integer> entry : quotas.entrySet()) {
            Quota quota = quotaRepository.findByUserAndQuotaType(user, entry.getKey()).orElseGet(() -> {
                Quota q = new Quota();
                q.setUser(user);
                q.setQuotaType(entry.getKey());
                return q;
            });
            quota.setTotal(entry.getValue() == null ? 0 : entry.getValue());
            quotaRepository.save(quota);
        }
    }

    @Transactional(readOnly = true)
    public List<Entitlement> getActiveEntitlements(User user) {
        return entitlementRepository.findByUserAndActiveTrueOrderByGrantedAtDesc(user);
    }

    @Transactional(readOnly = true)
    public Optional<UserPlan> getActivePlan(User user) {
        return userPlanRepository.findFirstByUserAndActiveTrueOrderByStartedAtDesc(user);
    }

    /**
     * Return minimal, non-customer-identifying proof that a paid catalog order
     * granted the exact immutable artifact advertised by MODstore.
     */
    @Transactional(readOnly = true)
    public Map<String, Object> catalogFulfillmentEvidence(String sourceOrderId, Long catalogId) {
        Map<String, Object> result = new HashMap<>();
        result.put("verified", false);
        if (sourceOrderId == null || sourceOrderId.isBlank() || catalogId == null || catalogId <= 0) {
            result.put("reason", "invalid_order_reference");
            return result;
        }
        Optional<Entitlement> entitlementRow = entitlementRepository.findBySourceOrderId(sourceOrderId);
        if (entitlementRow.isEmpty()) {
            result.put("reason", "entitlement_missing");
            return result;
        }
        Entitlement entitlement = entitlementRow.get();
        if (!entitlement.isActive() || !catalogId.equals(entitlement.getCatalogId())) {
            result.put("reason", "entitlement_inactive_or_mismatched");
            return result;
        }
        Optional<CatalogItem> itemRow = catalogItemRepository.findById(catalogId);
        if (itemRow.isEmpty()) {
            result.put("reason", "catalog_item_missing");
            return result;
        }
        CatalogItem item = itemRow.get();
        String pkgId = item.getPkgId() == null ? "" : item.getPkgId().trim();
        String version = item.getVersion() == null ? "" : item.getVersion().trim();
        String sha256 = item.getSha256() == null ? "" : item.getSha256().trim().toLowerCase();
        if (pkgId.isEmpty() || version.isEmpty() || !sha256.matches("[0-9a-f]{64}")) {
            result.put("reason", "catalog_artifact_identity_incomplete");
            return result;
        }
        if (entitlement.getGrantedAt() == null) {
            result.put("reason", "entitlement_granted_at_missing");
            return result;
        }
        result.put("verified", true);
        result.put("reason", "verified");
        result.put("artifact_id", "catalog:" + pkgId + "@" + version);
        result.put("artifact_sha256", sha256);
        result.put("artifact_kind", item.getArtifact() == null ? "" : item.getArtifact());
        result.put("fulfilled_at", entitlement.getGrantedAt());
        result.put("entitlement_type", entitlement.getEntitlementType());
        return result;
    }

    /**
     * Return an immutable activation receipt for a paid service plan.
     *
     * The receipt hash binds the paid order, plan and persisted activation
     * timestamps.  Customer acceptance is separate: it becomes verified only
     * after a quota that belongs to the purchased plan has real usage.
     */
    @Transactional(readOnly = true)
    public Map<String, Object> planFulfillmentEvidence(String sourceOrderId, String planId) {
        Map<String, Object> result = new HashMap<>();
        result.put("verified", false);
        if (sourceOrderId == null || sourceOrderId.isBlank()
                || planId == null || planId.isBlank()) {
            result.put("reason", "invalid_order_reference");
            return result;
        }
        Optional<Entitlement> entitlementRow = entitlementRepository.findBySourceOrderId(sourceOrderId);
        if (entitlementRow.isEmpty()) {
            result.put("reason", "entitlement_missing");
            return result;
        }
        Entitlement entitlement = entitlementRow.get();
        if (!entitlement.isActive() || !"plan".equalsIgnoreCase(entitlement.getEntitlementType())
                || entitlement.getUser() == null) {
            result.put("reason", "plan_entitlement_inactive_or_mismatched");
            return result;
        }
        Optional<UserPlan> userPlanRow = userPlanRepository.findByUserAndSourceOrderId(
                entitlement.getUser(), sourceOrderId);
        if (userPlanRow.isEmpty()) {
            result.put("reason", "user_plan_missing");
            return result;
        }
        UserPlan userPlan = userPlanRow.get();
        PlanTemplate plan = userPlan.getPlan();
        if (plan == null || plan.getId() == null
                || !planId.trim().equals(plan.getId().trim())) {
            result.put("reason", "user_plan_mismatched");
            return result;
        }
        if (userPlan.getStartedAt() == null || entitlement.getGrantedAt() == null) {
            result.put("reason", "plan_activation_timestamp_missing");
            return result;
        }

        String orderDigest = sha256Hex(sourceOrderId.trim());
        String normalizedPlanId = plan.getId().trim();
        String artifactId = "service-plan:" + normalizedPlanId + "@" + orderDigest.substring(0, 16);
        String artifactDescriptor = String.join("\n",
                "service-plan-activation.v1",
                normalizedPlanId,
                sourceOrderId.trim(),
                userPlan.getStartedAt().toString(),
                entitlement.getGrantedAt().toString());

        Map<String, Integer> contractedQuotas = parseContractedQuotas(plan.getQuotasJson());
        // A later upgrade deactivates the previous UserPlan, but it does not erase
        // the paid plan's historical activation.  Keep delivery verification tied
        // to the immutable activation timestamps while refusing to attribute the
        // current plan's quota usage to a superseded plan.
        List<Quota> usedContractedQuotas = userPlan.isActive()
                ? quotaRepository.findByUser(entitlement.getUser()).stream()
                        .filter(quota -> quota.getQuotaType() != null)
                        .filter(quota -> contractedQuotas.containsKey(quota.getQuotaType()))
                        .filter(quota -> quota.getUsed() > 0)
                        .toList()
                : List.of();
        int usageCount = usedContractedQuotas.stream().mapToInt(Quota::getUsed).sum();
        LocalDateTime acceptedAt = usedContractedQuotas.stream()
                .map(Quota::getUpdatedAt)
                .filter(value -> value != null)
                .max(Comparator.naturalOrder())
                .orElse(null);
        boolean acceptanceVerified = usageCount > 0 && acceptedAt != null;

        result.put("verified", true);
        result.put("reason", userPlan.isActive() ? "verified" : "verified_historical_activation");
        result.put("artifact_id", artifactId);
        result.put("artifact_sha256", sha256Hex(artifactDescriptor));
        result.put("artifact_kind", "service_plan_activation");
        result.put("fulfilled_at", userPlan.getStartedAt());
        result.put("acceptance_verified", acceptanceVerified);
        result.put(
                "acceptance_reason",
                acceptanceVerified
                        ? "verified_plan_usage"
                        : (userPlan.isActive() ? "usage_not_observed" : "historical_plan_superseded")
        );
        result.put("accepted_at", acceptedAt);
        return result;
    }

    private Map<String, Integer> parseContractedQuotas(String rawQuotas) {
        try {
            return objectMapper.readValue(rawQuotas == null ? "{}" : rawQuotas,
                    new TypeReference<Map<String, Integer>>() {});
        } catch (Exception exc) {
            log.warn("Unable to parse plan quota contract for fulfillment evidence", exc);
            return Map.of();
        }
    }

    private static String sha256Hex(String value) {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            return HexFormat.of().formatHex(digest.digest(value.getBytes(StandardCharsets.UTF_8)));
        } catch (NoSuchAlgorithmException exc) {
            throw new IllegalStateException("SHA-256 unavailable", exc);
        }
    }

    @Transactional(readOnly = true)
    public List<Quota> getQuotas(User user) {
        return quotaRepository.findByUser(user);
    }
    
    @Transactional
    public List<Purchase> getPurchases(User user) {
        return purchaseRepository.findByUserOrderByCreatedAtDesc(user);
    }
    
    @Transactional
    public long countPurchases(User user) {
        return purchaseRepository.countByUser(user);
    }

    @Transactional
    public void revokeOrderEntitlements(User user, String sourceOrderId) {
        entitlementRepository.findBySourceOrderId(sourceOrderId).ifPresent(entitlement -> {
            entitlement.setActive(false);
            entitlement.setExpiresAt(LocalDateTime.now());
            entitlementRepository.save(entitlement);
        });

        userPlanRepository.findByUserAndSourceOrderId(user, sourceOrderId).ifPresent(userPlan -> {
            userPlan.setActive(false);
            userPlan.setExpiresAt(LocalDateTime.now());
            userPlanRepository.save(userPlan);

            // The refunded plan should not keep granting quota after its entitlement is revoked.
            quotaRepository.findByUser(user).forEach(quota -> {
                quota.setTotal(Math.min(quota.getUsed(), quota.getTotal()));
                quotaRepository.save(quota);
            });
        });
    }

    @Transactional(readOnly = true)
    public boolean hasPurchasedOrActiveEntitlement(User user, Long catalogId) {
        if (user == null || catalogId == null || catalogId <= 0) {
            return false;
        }
        if (purchaseRepository.existsByUserAndCatalogId(user, catalogId)) {
            return true;
        }
        return entitlementRepository.existsByUserAndCatalogIdAndActiveTrue(user, catalogId);
    }
}
