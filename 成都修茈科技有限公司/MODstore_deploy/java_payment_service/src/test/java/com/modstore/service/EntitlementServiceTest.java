package com.modstore.service;

import com.modstore.model.*;
import com.modstore.repository.*;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.*;
import org.mockito.junit.jupiter.MockitoExtension;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Optional;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

@ExtendWith(MockitoExtension.class)
class EntitlementServiceTest {

    @Mock PurchaseRepository purchaseRepository;
    @Mock EntitlementRepository entitlementRepository;
    @Mock UserPlanRepository userPlanRepository;
    @Mock UserRepository userRepository;
    @Mock QuotaRepository quotaRepository;
    @Mock CatalogItemRepository catalogItemRepository;

    @InjectMocks EntitlementService entitlementService;

    private User user;

    @BeforeEach
    void setUp() {
        user = new User();
        user.setId(1L);
        user.setUsername("testuser");
        user.setPasswordHash("hash");
    }

    @Nested
    class CreatePurchase {
        @Test
        void createsPurchaseRecord() {
            when(purchaseRepository.save(any(Purchase.class))).thenAnswer(inv -> inv.getArgument(0));

            entitlementService.createPurchase(user, 42L, new BigDecimal("29.90"));

            verify(purchaseRepository).save(argThat(p ->
                    p.getUser().equals(user) &&
                    p.getCatalogId().equals(42L) &&
                    p.getAmount().compareTo(new BigDecimal("29.90")) == 0));
        }
    }

    @Nested
    class GrantCatalogEntitlement {
        @Test
        void grantsEntitlementWhenNoDuplicate() {
            when(entitlementRepository.findBySourceOrderId("OT-1")).thenReturn(Optional.empty());
            when(entitlementRepository.save(any(Entitlement.class))).thenAnswer(inv -> inv.getArgument(0));
            CatalogItem modItem = new CatalogItem();
            modItem.setId(42L);
            modItem.setArtifact("mod");
            when(catalogItemRepository.findById(42L)).thenReturn(Optional.of(modItem));

            entitlementService.grantCatalogEntitlement(user, 42L, "OT-1");

            verify(entitlementRepository).save(argThat(e ->
                    e.getUser().equals(user) &&
                    e.getCatalogId().equals(42L) &&
                    "mod".equals(e.getEntitlementType()) &&
                    "OT-1".equals(e.getSourceOrderId())));
        }

        @Test
        void grantsEmployeeEntitlementForEmployeePackAndIncrementsQuota() {
            when(entitlementRepository.findBySourceOrderId("OT-EMP")).thenReturn(Optional.empty());
            when(entitlementRepository.save(any(Entitlement.class))).thenAnswer(inv -> inv.getArgument(0));
            CatalogItem empItem = new CatalogItem();
            empItem.setId(99L);
            empItem.setArtifact("employee_pack");
            when(catalogItemRepository.findById(99L)).thenReturn(Optional.of(empItem));
            when(quotaRepository.findByUserAndQuotaType(user, "employee_count")).thenReturn(Optional.empty());
            when(quotaRepository.save(any(Quota.class))).thenAnswer(inv -> inv.getArgument(0));

            entitlementService.grantCatalogEntitlement(user, 99L, "OT-EMP");

            verify(entitlementRepository).save(argThat(e ->
                    "employee".equals(e.getEntitlementType()) && "OT-EMP".equals(e.getSourceOrderId())));
            verify(quotaRepository).save(argThat(q ->
                    "employee_count".equals(q.getQuotaType()) && q.getTotal() == 1));
        }

        @Test
        void skipsWhenEntitlementAlreadyExists() {
            Entitlement existing = new Entitlement();
            when(entitlementRepository.findBySourceOrderId("OT-2")).thenReturn(Optional.of(existing));

            entitlementService.grantCatalogEntitlement(user, 42L, "OT-2");

            verify(entitlementRepository, never()).save(any());
        }
    }

    @Nested
    class CatalogFulfillmentEvidence {
        @Test
        void verifiesExactActiveEntitlementAndImmutableArtifact() {
            Entitlement entitlement = new Entitlement();
            entitlement.setCatalogId(42L);
            entitlement.setActive(true);
            entitlement.setEntitlementType("mod");
            entitlement.setGrantedAt(java.time.LocalDateTime.of(2026, 7, 22, 20, 5));
            CatalogItem item = new CatalogItem();
            item.setId(42L);
            item.setPkgId("customer-value-pack");
            item.setVersion("1.2.3");
            item.setSha256("a".repeat(64));
            item.setArtifact("mod");
            when(entitlementRepository.findBySourceOrderId("OT-VALUE"))
                    .thenReturn(Optional.of(entitlement));
            when(catalogItemRepository.findById(42L)).thenReturn(Optional.of(item));

            var result = entitlementService.catalogFulfillmentEvidence("OT-VALUE", 42L);

            assertThat(result.get("verified")).isEqualTo(true);
            assertThat(result.get("artifact_id"))
                    .isEqualTo("catalog:customer-value-pack@1.2.3");
            assertThat(result.get("artifact_sha256")).isEqualTo("a".repeat(64));
            assertThat(result.get("fulfilled_at"))
                    .isEqualTo(java.time.LocalDateTime.of(2026, 7, 22, 20, 5));
        }

        @Test
        void rejectsCatalogRowsWithoutImmutableArtifactHash() {
            Entitlement entitlement = new Entitlement();
            entitlement.setCatalogId(42L);
            entitlement.setActive(true);
            entitlement.setGrantedAt(java.time.LocalDateTime.now());
            CatalogItem item = new CatalogItem();
            item.setId(42L);
            item.setPkgId("unhashed-pack");
            item.setVersion("1.0.0");
            item.setSha256("");
            when(entitlementRepository.findBySourceOrderId("OT-UNHASHED"))
                    .thenReturn(Optional.of(entitlement));
            when(catalogItemRepository.findById(42L)).thenReturn(Optional.of(item));

            var result = entitlementService.catalogFulfillmentEvidence("OT-UNHASHED", 42L);

            assertThat(result.get("verified")).isEqualTo(false);
            assertThat(result.get("reason"))
                    .isEqualTo("catalog_artifact_identity_incomplete");
        }
    }

    @Nested
    class PlanFulfillmentEvidence {
        @Test
        void verifiesActivationAndSeparatesObservedUsageAcceptance() {
            LocalDateTime startedAt = LocalDateTime.of(2026, 7, 22, 20, 5);
            LocalDateTime acceptedAt = LocalDateTime.of(2026, 7, 22, 20, 30);
            PlanTemplate plan = new PlanTemplate();
            plan.setId("pro");
            plan.setQuotasJson("{\"ai_calls\":100,\"storage\":50}");
            Entitlement entitlement = new Entitlement();
            entitlement.setUser(user);
            entitlement.setActive(true);
            entitlement.setEntitlementType("plan");
            entitlement.setGrantedAt(startedAt);
            UserPlan userPlan = new UserPlan();
            userPlan.setUser(user);
            userPlan.setPlan(plan);
            userPlan.setActive(true);
            userPlan.setStartedAt(startedAt);
            Quota usedQuota = new Quota();
            usedQuota.setUser(user);
            usedQuota.setQuotaType("ai_calls");
            usedQuota.setUsed(3);
            usedQuota.setUpdatedAt(acceptedAt);
            Quota unrelatedQuota = new Quota();
            unrelatedQuota.setUser(user);
            unrelatedQuota.setQuotaType("employee_count");
            unrelatedQuota.setUsed(99);
            unrelatedQuota.setUpdatedAt(acceptedAt.plusHours(1));

            when(entitlementRepository.findBySourceOrderId("OT-PLAN-VALUE"))
                    .thenReturn(Optional.of(entitlement));
            when(userPlanRepository.findByUserAndSourceOrderId(user, "OT-PLAN-VALUE"))
                    .thenReturn(Optional.of(userPlan));
            when(quotaRepository.findByUser(user)).thenReturn(List.of(usedQuota, unrelatedQuota));

            var result = entitlementService.planFulfillmentEvidence("OT-PLAN-VALUE", "pro");

            assertThat(result.get("verified")).isEqualTo(true);
            assertThat(result.get("artifact_id").toString())
                    .startsWith("service-plan:pro@");
            assertThat(result.get("artifact_sha256").toString()).matches("[0-9a-f]{64}");
            assertThat(result.get("artifact_kind")).isEqualTo("service_plan_activation");
            assertThat(result.get("acceptance_verified")).isEqualTo(true);
            assertThat(result.get("acceptance_reason")).isEqualTo("verified_plan_usage");
            assertThat(result.get("accepted_at")).isEqualTo(acceptedAt);
        }

        @Test
        void verifiesSupersededActivationWithoutBorrowingCurrentPlanUsage() {
            LocalDateTime startedAt = LocalDateTime.of(2026, 7, 1, 9, 0);
            PlanTemplate plan = new PlanTemplate();
            plan.setId("basic");
            plan.setQuotasJson("{\"ai_calls\":10}");
            Entitlement entitlement = new Entitlement();
            entitlement.setUser(user);
            entitlement.setActive(true);
            entitlement.setEntitlementType("plan");
            entitlement.setGrantedAt(startedAt);
            UserPlan supersededPlan = new UserPlan();
            supersededPlan.setUser(user);
            supersededPlan.setPlan(plan);
            supersededPlan.setActive(false);
            supersededPlan.setStartedAt(startedAt);

            when(entitlementRepository.findBySourceOrderId("OT-BASIC-HISTORY"))
                    .thenReturn(Optional.of(entitlement));
            when(userPlanRepository.findByUserAndSourceOrderId(user, "OT-BASIC-HISTORY"))
                    .thenReturn(Optional.of(supersededPlan));

            var result = entitlementService.planFulfillmentEvidence(
                    "OT-BASIC-HISTORY", "basic");

            assertThat(result.get("verified")).isEqualTo(true);
            assertThat(result.get("reason")).isEqualTo("verified_historical_activation");
            assertThat(result.get("artifact_sha256").toString()).matches("[0-9a-f]{64}");
            assertThat(result.get("acceptance_verified")).isEqualTo(false);
            assertThat(result.get("acceptance_reason")).isEqualTo("historical_plan_superseded");
            verify(quotaRepository, never()).findByUser(user);
        }
    }

    @Nested
    class ActivatePlan {
        @Test
        void deactivatesPreviousPlanAndActivatesNew() {
            UserPlan oldPlan = new UserPlan();
            oldPlan.setActive(true);
            when(userPlanRepository.findFirstByUserAndActiveTrueOrderByStartedAtDesc(user))
                    .thenReturn(Optional.of(oldPlan));
            when(userPlanRepository.save(any(UserPlan.class))).thenAnswer(inv -> inv.getArgument(0));
            when(entitlementRepository.save(any(Entitlement.class))).thenAnswer(inv -> inv.getArgument(0));

            PlanTemplate plan = new PlanTemplate();
            plan.setId("pro");
            plan.setQuotasJson("{\"ai_calls\":100}");

            Quota existingQuota = new Quota();
            existingQuota.setUser(user);
            existingQuota.setQuotaType("ai_calls");
            when(quotaRepository.findByUserAndQuotaType(user, "ai_calls")).thenReturn(Optional.of(existingQuota));
            when(quotaRepository.save(any(Quota.class))).thenAnswer(inv -> inv.getArgument(0));

            entitlementService.activatePlan(user, plan, "OT-PLAN1");

            verify(userPlanRepository).save(argThat(up -> !up.isActive()));
            verify(userPlanRepository).save(argThat(up -> up.isActive() && "pro".equals(up.getPlan().getId())));
            verify(entitlementRepository).save(argThat(e -> "plan".equals(e.getEntitlementType())));
            assertThat(user.getAccountState()).isEqualTo("active");
            verify(userRepository).save(user);
            verify(quotaRepository).save(argThat(q -> q.getTotal() == 100));
        }

        @Test
        void handlesMalformedQuotasJson() {
            when(userPlanRepository.findFirstByUserAndActiveTrueOrderByStartedAtDesc(user))
                    .thenReturn(Optional.empty());
            when(userPlanRepository.save(any(UserPlan.class))).thenAnswer(inv -> inv.getArgument(0));
            when(entitlementRepository.save(any(Entitlement.class))).thenAnswer(inv -> inv.getArgument(0));

            PlanTemplate plan = new PlanTemplate();
            plan.setId("bad");
            plan.setQuotasJson("not-json");

            entitlementService.activatePlan(user, plan, "OT-PLAN2");

            verify(quotaRepository, never()).save(any());
        }

        @Test
        void handlesNullQuotasJson() {
            when(userPlanRepository.findFirstByUserAndActiveTrueOrderByStartedAtDesc(user))
                    .thenReturn(Optional.empty());
            when(userPlanRepository.save(any(UserPlan.class))).thenAnswer(inv -> inv.getArgument(0));
            when(entitlementRepository.save(any(Entitlement.class))).thenAnswer(inv -> inv.getArgument(0));

            PlanTemplate plan = new PlanTemplate();
            plan.setId("null-q");
            plan.setQuotasJson(null);

            entitlementService.activatePlan(user, plan, "OT-PLAN3");

            verify(quotaRepository, never()).save(any());
        }

        @Test
        void createsNewQuotaWhenNotExists() {
            when(userPlanRepository.findFirstByUserAndActiveTrueOrderByStartedAtDesc(user))
                    .thenReturn(Optional.empty());
            when(userPlanRepository.save(any(UserPlan.class))).thenAnswer(inv -> inv.getArgument(0));
            when(entitlementRepository.save(any(Entitlement.class))).thenAnswer(inv -> inv.getArgument(0));
            when(quotaRepository.findByUserAndQuotaType(user, "storage")).thenReturn(Optional.empty());
            when(quotaRepository.save(any(Quota.class))).thenAnswer(inv -> inv.getArgument(0));

            PlanTemplate plan = new PlanTemplate();
            plan.setId("storage-plan");
            plan.setQuotasJson("{\"storage\":50}");

            entitlementService.activatePlan(user, plan, "OT-PLAN4");

            verify(quotaRepository).save(argThat(q ->
                    "storage".equals(q.getQuotaType()) && q.getTotal() == 50));
        }
    }

    @Nested
    class HasPurchasedOrActiveEntitlement {
        @Test
        void returnsTrueWhenPurchased() {
            when(purchaseRepository.existsByUserAndCatalogId(user, 42L)).thenReturn(true);

            assertThat(entitlementService.hasPurchasedOrActiveEntitlement(user, 42L)).isTrue();
        }

        @Test
        void returnsTrueWhenActiveEntitlement() {
            when(purchaseRepository.existsByUserAndCatalogId(user, 42L)).thenReturn(false);
            when(entitlementRepository.existsByUserAndCatalogIdAndActiveTrue(user, 42L)).thenReturn(true);

            assertThat(entitlementService.hasPurchasedOrActiveEntitlement(user, 42L)).isTrue();
        }

        @Test
        void returnsFalseWhenNeither() {
            when(purchaseRepository.existsByUserAndCatalogId(user, 42L)).thenReturn(false);
            when(entitlementRepository.existsByUserAndCatalogIdAndActiveTrue(user, 42L)).thenReturn(false);

            assertThat(entitlementService.hasPurchasedOrActiveEntitlement(user, 42L)).isFalse();
        }

        @Test
        void returnsFalseForNullUser() {
            assertThat(entitlementService.hasPurchasedOrActiveEntitlement(null, 42L)).isFalse();
        }

        @Test
        void returnsFalseForNullCatalogId() {
            assertThat(entitlementService.hasPurchasedOrActiveEntitlement(user, null)).isFalse();
        }

        @Test
        void returnsFalseForZeroCatalogId() {
            assertThat(entitlementService.hasPurchasedOrActiveEntitlement(user, 0L)).isFalse();
        }
    }

    @Nested
    class RevokeOrderEntitlements {
        @Test
        void revokesEntitlementAndDeactivatesPlan() {
            Entitlement entitlement = new Entitlement();
            entitlement.setActive(true);
            when(entitlementRepository.findBySourceOrderId("OT-REV1")).thenReturn(Optional.of(entitlement));

            UserPlan userPlan = new UserPlan();
            userPlan.setActive(true);
            when(userPlanRepository.findByUserAndSourceOrderId(user, "OT-REV1")).thenReturn(Optional.of(userPlan));

            Quota q1 = new Quota();
            q1.setTotal(100);
            q1.setUsed(30);
            when(quotaRepository.findByUser(user)).thenReturn(java.util.List.of(q1));

            entitlementService.revokeOrderEntitlements(user, "OT-REV1");

            assertThat(entitlement.isActive()).isFalse();
            assertThat(entitlement.getExpiresAt()).isNotNull();
            assertThat(userPlan.isActive()).isFalse();
            assertThat(q1.getTotal()).isEqualTo(30);
        }

        @Test
        void noopsWhenNoEntitlementOrPlan() {
            when(entitlementRepository.findBySourceOrderId("OT-REV2")).thenReturn(Optional.empty());
            when(userPlanRepository.findByUserAndSourceOrderId(user, "OT-REV2")).thenReturn(Optional.empty());

            entitlementService.revokeOrderEntitlements(user, "OT-REV2");

            verify(entitlementRepository, never()).save(any());
            verify(userPlanRepository, never()).save(any());
        }
    }
}
