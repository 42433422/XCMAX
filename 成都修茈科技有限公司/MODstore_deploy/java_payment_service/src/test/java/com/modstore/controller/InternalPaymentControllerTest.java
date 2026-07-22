package com.modstore.controller;

import com.modstore.model.Order;
import com.modstore.repository.UserRepository;
import com.modstore.service.OrderService;
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
import static org.mockito.Mockito.when;

class InternalPaymentControllerTest {

    private OrderService orderService;
    private InternalPaymentController controller;

    @BeforeEach
    void setUp() {
        orderService = mock(OrderService.class);
        controller = new InternalPaymentController(mock(UserRepository.class), orderService);
        ReflectionTestUtils.setField(controller, "internalApiKey", "test-internal-key");
        ReflectionTestUtils.setField(controller, "deployTier", "production");
        ReflectionTestUtils.setField(controller, "alipayDebug", false);
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
        assertTrue(row.keySet().stream().noneMatch(key -> key.contains("user")));
        assertTrue(row.keySet().stream().noneMatch(key -> key.contains("buyer")));
    }
}
