package com.modstore.controller;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyMap;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.modstore.model.Entitlement;
import com.modstore.model.Order;
import com.modstore.model.PlanTemplate;
import com.modstore.model.Quota;
import com.modstore.model.Transaction;
import com.modstore.model.User;
import com.modstore.model.UserPlan;
import com.modstore.repository.PlanTemplateRepository;
import com.modstore.repository.UserPlanRepository;
import com.modstore.service.AlipayService;
import com.modstore.service.CurrentUserService;
import com.modstore.service.EntitlementService;
import com.modstore.service.OrderService;
import com.modstore.service.PaymentMetrics;
import com.modstore.service.SecurityService;
import com.modstore.service.WalletService;
import com.modstore.service.WechatPayService;
import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.web.server.ResponseStatusException;

class PaymentControllerContractTest {

    private OrderService orderService;
    private AlipayService alipayService;
    private SecurityService securityService;
    private CurrentUserService currentUserService;
    private PlanTemplateRepository planTemplateRepository;
    private UserPlanRepository userPlanRepository;
    private EntitlementService entitlementService;
    private WalletService walletService;
    private WechatPayService wechatPayService;
    private PaymentMetrics paymentMetrics;
    private PaymentController controller;
    private User user;

    @BeforeEach
    void setUp() {
        orderService = mock(OrderService.class);
        alipayService = mock(AlipayService.class);
        securityService = mock(SecurityService.class);
        currentUserService = mock(CurrentUserService.class);
        planTemplateRepository = mock(PlanTemplateRepository.class);
        userPlanRepository = mock(UserPlanRepository.class);
        entitlementService = mock(EntitlementService.class);
        walletService = mock(WalletService.class);
        wechatPayService = mock(WechatPayService.class);
        paymentMetrics = mock(PaymentMetrics.class);
        controller = new PaymentController(
                orderService,
                alipayService,
                securityService,
                currentUserService,
                planTemplateRepository,
                userPlanRepository,
                entitlementService,
                walletService,
                wechatPayService,
                paymentMetrics);
        ReflectionTestUtils.setField(controller, "publicOrigin", " https://pay.example.com/ ");
        ReflectionTestUtils.setField(controller, "marketPrefix", "market/");

        user = new User();
        user.setId(7L);
        when(currentUserService.requireCurrentUser()).thenReturn(user);
        when(userPlanRepository.findByUserAndActiveTrue(user)).thenReturn(List.of());
        when(userPlanRepository.findFirstByUserAndActiveTrueOrderByStartedAtDesc(user))
                .thenReturn(Optional.empty());
        when(walletService.getTransactionsForOrder(any(), any())).thenReturn(List.of());
    }

    @Test
    void catalogMembershipAndDiagnosticsResponsesPreservePublicContract() {
        PlanTemplate basic = plan("plan_basic", "VIP", "[\"feature-a\"]");
        PlanTemplate unknown = plan("plan_custom", "Custom", "not-json");
        PlanTemplate account = plan("saas-trial-30", "Account", "[]");
        when(planTemplateRepository.findByActiveTrue()).thenReturn(List.of(unknown, account, basic));

        List<?> plans = (List<?>) controller.getPlans().get("plans");
        assertEquals(2, plans.size());
        assertFalse(((List<?>) ((Map<?, ?>) plans.get(0)).get("features")).isEmpty());
        assertFalse(((List<?>) controller.getAccountPlans().get("plans")).isEmpty());

        Entitlement entitlement = new Entitlement();
        entitlement.setId(1L);
        entitlement.setCatalogId(2L);
        entitlement.setEntitlementType("mod");
        entitlement.setSourceOrderId("OT-1");
        entitlement.setMetadataJson("{}");
        entitlement.setGrantedAt(LocalDateTime.now());
        when(entitlementService.getActiveEntitlements(user)).thenReturn(List.of(entitlement));
        assertEquals(1, controller.entitlements().get("total"));
        assertTrue(controller.usageMetrics().containsKey("success_rate"));

        when(wechatPayService.configured()).thenReturn(true);
        when(alipayService.notifyUrlDiagnostics())
                .thenReturn(Map.of("effective_notify_url", "https://secret", "valid", true));
        assertFalse(((Map<?, ?>) controller.diagnostics().get("alipay_async_notify"))
                .containsKey("effective_notify_url"));
        user.setAdmin(true);
        assertTrue(((Map<?, ?>) controller.diagnostics().get("alipay_async_notify"))
                .containsKey("effective_notify_url"));
        assertFalse((Boolean) controller.refund(Map.of()).get("ok"));
        user.setAdmin(false);
        assertFalse((Boolean) controller.refund(Map.of()).get("ok"));
    }

    @Test
    void signingEnforcesTierRulesAndReturnsProviderSignature() {
        Map<String, Object> resolved = new HashMap<>(Map.of(
                "subject", "VIP",
                "total_amount", "99.00",
                "order_kind", "plan",
                "item_id", 0,
                "plan_id", "plan_basic"));
        when(orderService.resolveCheckoutFields(anyMap(), eq(user))).thenReturn(resolved);
        when(securityService.generateRequestId()).thenReturn("req-1");
        when(securityService.signCheckout(anyMap())).thenReturn("signed");

        Map<String, Object> signed = controller.signCheckout(new HashMap<>(Map.of("plan_id", "plan_basic")));
        assertEquals("signed", signed.get("signature"));
        assertEquals("req-1", signed.get("request_id"));

        UserPlan higher = activePlan("plan_svip4");
        when(userPlanRepository.findByUserAndActiveTrue(user)).thenReturn(List.of(higher));
        assertThrows(
                ResponseStatusException.class,
                () -> controller.signCheckout(new HashMap<>(Map.of("plan_id", "plan_basic"))));

        when(userPlanRepository.findByUserAndActiveTrue(user)).thenReturn(List.of());
        assertThrows(
                ResponseStatusException.class,
                () -> controller.signCheckout(new HashMap<>(Map.of("plan_id", "plan_svip2"))));

        when(userPlanRepository.findFirstByUserAndActiveTrueOrderByStartedAtDesc(user))
                .thenReturn(Optional.of(activePlan("plan_enterprise")));
        when(orderService.resolveCheckoutFields(anyMap(), eq(user)))
                .thenReturn(new HashMap<>(resolved));
        assertEquals("signed", controller.signCheckout(
                        new HashMap<>(Map.of("plan_id", "plan_svip2")))
                .get("signature"));
    }

    @Test
    void checkoutHandlesReplaySignaturesProvidersAndFailures() {
        Map<String, Object> request = checkoutRequest("alipay");
        when(securityService.checkReplayAttack("req-1", 123L)).thenReturn(true);
        assertFalse((Boolean) controller.checkout(request).get("ok"));

        when(securityService.checkReplayAttack("req-1", 123L)).thenReturn(false);
        when(securityService.verifySignature(request, "sig")).thenReturn(false);
        assertFalse((Boolean) controller.checkout(request).get("ok"));

        when(securityService.verifySignature(anyMap(), eq("sig"))).thenReturn(true);
        when(orderService.resolveCheckoutFields(anyMap(), eq(user))).thenReturn(checkoutFields());
        Order order = order("OT-created", user);
        when(orderService.createOrder(any(), any(), any(), any(), any(), any(), any(), any()))
                .thenReturn(order);
        when(alipayService.createPagePay(any(), any(), any(), any()))
                .thenReturn(Map.of(
                        "ok", true,
                        "type", "redirect",
                        "redirect_url", "https://alipay.example/pay"));
        Map<String, Object> paid = controller.checkout(request);
        assertTrue((Boolean) paid.get("ok"));
        assertEquals("redirect", paid.get("type"));
        verify(orderService).updatePaymentMetadata(eq("OT-created"), eq("redirect"), eq(null));

        when(alipayService.createPagePay(any(), any(), any(), any()))
                .thenReturn(Map.of("ok", false, "message", "  provider down  "));
        assertEquals("provider down", controller.checkout(request).get("message"));
        when(alipayService.createPagePay(any(), any(), any(), any()))
                .thenReturn(Map.of("ok", false));
        assertTrue(String.valueOf(controller.checkout(request).get("message")).contains("无详细说明"));

        Map<String, Object> wechatRequest = checkoutRequest("wechat");
        when(wechatPayService.configured()).thenReturn(false);
        assertTrue(String.valueOf(controller.checkout(wechatRequest).get("message")).contains("未配置"));
        when(wechatPayService.configured()).thenReturn(true);
        when(wechatPayService.createNativePay(any(), any(), any()))
                .thenReturn(Map.of("ok", true, "type", "qrcode", "qr_code", "weixin://pay"));
        assertTrue((Boolean) controller.checkout(wechatRequest).get("ok"));

        assertFalse((Boolean) controller.checkout(Map.of()).get("ok"));
        doThrow(new IllegalStateException("boom"))
                .when(securityService)
                .checkReplayAttack("req-error", 123L);
        Map<String, Object> errorRequest = checkoutRequest("alipay");
        errorRequest.put("request_id", "req-error");
        assertEquals("系统内部错误", controller.checkout(errorRequest).get("message"));
    }

    @Test
    void orderQueryListCancelAndBackfillHonorOwnershipAndFailureModes() {
        assertFalse((Boolean) controller.queryOrder("missing", false).get("ok"));

        User owner = new User();
        owner.setId(99L);
        Order order = order("OT-1", owner);
        when(orderService.findByOutTradeNo("OT-1")).thenReturn(Optional.of(order));
        assertEquals("无权查看该订单", controller.queryOrder("OT-1", false).get("message"));

        user.setAdmin(true);
        Transaction transaction = transaction();
        when(walletService.getTransactionsForOrder(owner, "OT-1")).thenReturn(List.of(transaction));
        when(orderService.findByOutTradeNo("OT-1"))
                .thenReturn(Optional.of(order), Optional.of(order), Optional.of(order));
        assertEquals("OT-1", controller.queryOrder("OT-1", false).get("out_trade_no"));
        doThrow(new IllegalStateException("provider unavailable"))
                .when(orderService)
                .reconcileWithAlipayIfUnfulfilled("OT-1");
        assertEquals("OT-1", controller.queryOrder("OT-1", true).get("out_trade_no"));

        when(orderService.findByUser(user, "paid", 20, 1)).thenReturn(List.of(order));
        when(orderService.countByUser(user, "paid")).thenReturn(1L);
        assertEquals(1L, controller.listOrders(" paid ", 20, 1).get("total"));
        when(orderService.findByUser(user, null, 20, 1)).thenReturn(List.of());
        assertEquals(0, ((List<?>) controller.listOrders(" ", 20, 1).get("orders")).size());

        when(orderService.dismissNonActiveOrdersForUser(user)).thenReturn(3);
        assertEquals(3, controller.dismissNonActiveOrders().get("dismissed"));
        when(orderService.cancelPendingOrder(user, "OT-1")).thenReturn(true);
        assertEquals("closed", controller.cancelOrder("OT-1").get("status"));
        when(orderService.cancelPendingOrder(user, "OT-2")).thenReturn(false);
        assertEquals("unchanged", controller.cancelOrder("OT-2").get("status"));

        user.setAdmin(false);
        assertFalse((Boolean) controller.reconcileMembershipTokensBackfill().get("ok"));
        user.setAdmin(true);
        when(orderService.backfillPlanMembershipTokenGrants())
                .thenReturn(Map.of("ok", true, "updated", 2));
        assertEquals(2, controller.reconcileMembershipTokensBackfill().get("updated"));
        when(orderService.backfillPlanMembershipTokenGrants()).thenThrow(new IllegalStateException("db"));
        assertFalse((Boolean) controller.reconcileMembershipTokensBackfill().get("ok"));
    }

    @Test
    void myPlanMapsEveryPublishedMembershipTierAndQuotaBoundary() {
        Quota quota = new Quota();
        quota.setQuotaType("tokens");
        quota.setTotal(10);
        quota.setUsed(15);
        when(entitlementService.getQuotas(user)).thenReturn(List.of(quota));

        assertEquals("free", ((Map<?, ?>) controller.myPlan().get("membership")).get("tier"));
        for (String planId : List.of(
                "plan_basic",
                "plan_pro",
                "plan_enterprise",
                "plan_svip2",
                "plan_svip3",
                "plan_svip4",
                "plan_svip5",
                "plan_svip6",
                "plan_svip7",
                "plan_svip8")) {
            UserPlan active = activePlan(planId);
            when(entitlementService.getActivePlan(user)).thenReturn(Optional.of(active));
            Map<?, ?> membership = (Map<?, ?>) controller.myPlan().get("membership");
            assertTrue((Boolean) membership.get("is_member"));
        }
    }

    private static Map<String, Object> checkoutRequest(String channel) {
        return new HashMap<>(Map.of(
                "request_id", "req-1",
                "timestamp", 123L,
                "signature", "sig",
                "pay_channel", channel,
                "plan_id", "plan_basic"));
    }

    private static Map<String, Object> checkoutFields() {
        return new HashMap<>(Map.of(
                "subject", "VIP membership",
                "total_amount", "99.00",
                "order_kind", "plan",
                "item_id", 0,
                "plan_id", "plan_basic"));
    }

    private static PlanTemplate plan(String id, String name, String featuresJson) {
        PlanTemplate plan = new PlanTemplate();
        plan.setId(id);
        plan.setName(name);
        plan.setDescription(name + " description");
        plan.setPrice(new BigDecimal("99.00"));
        plan.setFeaturesJson(featuresJson);
        return plan;
    }

    private static UserPlan activePlan(String planId) {
        UserPlan userPlan = new UserPlan();
        userPlan.setId(10L);
        userPlan.setPlan(plan(planId, planId, "[]"));
        userPlan.setStartedAt(LocalDateTime.now().minusDays(1));
        return userPlan;
    }

    private static Order order(String outTradeNo, User owner) {
        Order order = new Order();
        order.setOutTradeNo(outTradeNo);
        order.setTradeNo("TRADE-1");
        order.setUser(owner);
        order.setStatus("paid");
        order.setSubject("VIP");
        order.setTotalAmount(new BigDecimal("99.00"));
        order.setOrderKind("plan");
        order.setPlanId("plan_basic");
        order.setCreatedAt(LocalDateTime.now());
        order.setUpdatedAt(LocalDateTime.now());
        return order;
    }

    private static Transaction transaction() {
        Transaction transaction = new Transaction();
        transaction.setId(1L);
        transaction.setAmount(BigDecimal.ONE);
        transaction.setTransactionType("credit");
        transaction.setStatus("success");
        transaction.setDescription("grant");
        transaction.setBalanceBefore(BigDecimal.ZERO);
        transaction.setBalanceAfter(BigDecimal.ONE);
        transaction.setCreatedAt(LocalDateTime.now());
        return transaction;
    }
}
