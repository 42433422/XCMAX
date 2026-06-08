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
import com.modstore.repository.PurchaseRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.time.LocalDateTime;
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
