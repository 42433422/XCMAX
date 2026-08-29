package com.modstore.controller;

import com.modstore.model.Order;
import com.modstore.model.User;
import com.modstore.repository.UserRepository;
import com.modstore.service.AlipayService;
import com.modstore.service.OrderService;
import com.modstore.service.WechatPayService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.web.server.ResponseStatusException;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class InternalPaymentControllerTest {

    private OrderService orderService;
    private InternalPaymentController controller;
    private UserRepository userRepository;
    private AlipayService alipayService;
    private WechatPayService wechatPayService;

    @BeforeEach
    void setUp() {
        orderService = mock(OrderService.class);
        userRepository = mock(UserRepository.class);
        alipayService = mock(AlipayService.class);
        wechatPayService = mock(WechatPayService.class);
        controller = new InternalPaymentController(
                userRepository,
                orderService,
                alipayService,
                wechatPayService
        );
        ReflectionTestUtils.setField(controller, "internalApiKey", "test-internal-key");
        ReflectionTestUtils.setField(controller, "deployTier", "production");
        ReflectionTestUtils.setField(controller, "alipayDebug", false);
        ReflectionTestUtils.setField(controller, "publicOrigin", "https://www.xiu-ci.com");
        ReflectionTestUtils.setField(controller, "marketPrefix", "/market");
    }

    @Test
    void customDeliveryCheckoutCreatesDedicatedServiceOrder() {
        User user = new User();
        user.setId(7L);
        when(userRepository.findById(7L)).thenReturn(java.util.Optional.of(user));
        when(orderService.createOrder(
                eq(user), any(), eq("合同复核新增开发"), eq(new BigDecimal("8800.00")),
                eq("custom_delivery"), eq(null), eq(null), any()
        )).thenAnswer(invocation -> {
            Order order = new Order();
            order.setOutTradeNo(invocation.getArgument(1));
            return order;
        });
        when(alipayService.createPagePay(
                any(), eq("合同复核新增开发"), eq(new BigDecimal("8800.00")), any()
        )).thenReturn(Map.of(
                "ok", true,
                "type", "page",
                "redirect_url", "https://alipay.example/pay"
        ));

        Map<String, Object> result = controller.customDeliveryCheckout(
                "test-internal-key",
                Map.of(
                        "user_id", 7,
                        "ticket_no", "CD202608290001",
                        "subject", "合同复核新增开发",
                        "total_amount", "8800.00",
                        "pay_channel", "alipay"
                )
        );

        assertEquals(true, result.get("ok"));
        assertEquals("custom_delivery", result.get("order_kind"));
        assertEquals("8800.00", result.get("total_amount"));
        assertEquals("https://alipay.example/pay", result.get("redirect_url"));
        assertTrue(String.valueOf(result.get("checkout_path")).startsWith("/market/checkout/CDP"));
        verify(orderService).updatePaymentMetadata(any(), eq("page"), eq(null));
    }

    @Test
    void valueEvidenceRequiresInternalKey() {
        assertThrows(
                ResponseStatusException.class,
                () -> controller.valueEvidence("wrong-key", 90, 1000, 0)
        );
    }

    @Test
    @SuppressWarnings("unchecked")
    void valueEvidenceReturnsOnlyMinimalProviderProof() {
        Order order = new Order();
        order.setOutTradeNo("customer-order-001");
        order.setStatus("paid");
        order.setSubject("Customer delivery");
        order.setOrderKind("item");
        order.setItemId(42L);
        order.setTotalAmount(new BigDecimal("99.00"));
        order.setPaidAt(LocalDateTime.of(2026, 7, 22, 20, 0));
        order.setPayType("page");
        order.setTradeNo("provider-trade-001");
        order.setRefundStatus("none");
        order.setFulfilled(true);
        when(orderService.getCustomerValueFulfillmentEvidence(order)).thenReturn(Map.of(
                "verified", true,
                "reason", "verified",
                "artifact_id", "catalog:customer-value-pack@1.2.3",
                "artifact_sha256", "a".repeat(64),
                "fulfilled_at", LocalDateTime.of(2026, 7, 22, 20, 5)
        ));
        when(orderService.findPaidValueEvidenceSince(any(), eq(1000), eq(0)))
                .thenReturn(List.of(order));
        when(orderService.countPaidValueEvidenceSince(any())).thenReturn(1L);

        Map<String, Object> result = controller.valueEvidence(
                "test-internal-key",
                90,
                1000,
                0
        );
        List<Map<String, Object>> rows = (List<Map<String, Object>>) result.get("orders");
        Map<String, Object> row = rows.get(0);

        assertEquals("java_postgresql", result.get("source"));
        assertEquals("production", result.get("environment"));
        assertEquals("alipay", row.get("payment_provider"));
        assertEquals("java_gateway_verified", row.get("provider_verification"));
        assertEquals("production", row.get("payment_environment"));
        assertEquals("2026-07-22T12:00:00Z", row.get("paid_at"));
        assertEquals("item", row.get("order_kind"));
        assertEquals(42L, row.get("item_id"));
        assertEquals("", row.get("plan_id"));
        assertEquals(true, row.get("fulfillment_verified"));
        assertEquals("catalog:customer-value-pack@1.2.3", row.get("fulfillment_artifact_id"));
        assertEquals("a".repeat(64), row.get("fulfillment_artifact_sha256"));
        assertEquals("2026-07-22T12:05:00Z", row.get("fulfilled_at"));
        assertEquals(false, row.get("acceptance_verified"));
        assertEquals("", row.get("accepted_at"));
        assertTrue(row.keySet().stream().noneMatch(key -> key.contains("user")));
        assertTrue(row.keySet().stream().noneMatch(key -> key.contains("buyer")));
    }

    @Test
    @SuppressWarnings("unchecked")
    void valueEvidenceExportsPlanActivationAndObservedUsageWithoutCustomerIdentity() {
        Order order = new Order();
        order.setOutTradeNo("customer-plan-order-001");
        order.setStatus("paid");
        order.setSubject("Customer plan");
        order.setOrderKind("plan");
        order.setPlanId("pro");
        order.setTotalAmount(new BigDecimal("19.90"));
        order.setPaidAt(LocalDateTime.of(2026, 7, 22, 20, 0));
        order.setPayType("page");
        order.setTradeNo("provider-plan-trade-001");
        order.setRefundStatus("none");
        order.setFulfilled(true);
        when(orderService.getCustomerValueFulfillmentEvidence(order)).thenReturn(Map.of(
                "verified", true,
                "reason", "verified",
                "artifact_id", "service-plan:pro@0123456789abcdef",
                "artifact_sha256", "b".repeat(64),
                "artifact_kind", "service_plan_activation",
                "fulfilled_at", LocalDateTime.of(2026, 7, 22, 20, 5),
                "acceptance_verified", true,
                "acceptance_reason", "verified_plan_usage",
                "accepted_at", LocalDateTime.of(2026, 7, 22, 20, 30)
        ));
        when(orderService.findPaidValueEvidenceSince(any(), eq(1000), eq(0)))
                .thenReturn(List.of(order));
        when(orderService.countPaidValueEvidenceSince(any())).thenReturn(1L);

        Map<String, Object> result = controller.valueEvidence(
                "test-internal-key",
                90,
                1000,
                0
        );
        Map<String, Object> row = ((List<Map<String, Object>>) result.get("orders")).get(0);

        assertEquals("plan", row.get("order_kind"));
        assertEquals("pro", row.get("plan_id"));
        assertEquals("service_plan_activation", row.get("fulfillment_artifact_kind"));
        assertEquals(true, row.get("acceptance_verified"));
        assertEquals("verified_plan_usage", row.get("acceptance_reason"));
        assertEquals("2026-07-22T12:30:00Z", row.get("accepted_at"));
        assertTrue(row.keySet().stream().noneMatch(key -> key.contains("user")));
        assertTrue(row.keySet().stream().noneMatch(key -> key.contains("buyer")));
    }
}
