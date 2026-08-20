package com.modstore.controller;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import com.modstore.model.Order;
import com.modstore.model.Refund;
import com.modstore.model.User;
import com.modstore.service.CurrentUserService;
import com.modstore.service.RefundService;
import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

class RefundControllerContractTest {

    private RefundService refundService;
    private CurrentUserService currentUserService;
    private RefundController controller;
    private User user;
    private Refund refund;

    @BeforeEach
    void setUp() {
        refundService = mock(RefundService.class);
        currentUserService = mock(CurrentUserService.class);
        controller = new RefundController(refundService, currentUserService);
        user = new User();
        user.setId(9L);
        when(currentUserService.requireCurrentUser()).thenReturn(user);
        refund = refund();
    }

    @Test
    void applyAndReviewReturnStableSuccessAndFailurePayloads() {
        when(refundService.apply(user, "OT-1", "duplicate")).thenReturn(refund);
        Map<String, Object> applied = controller.apply(Map.of("order_no", "OT-1", "reason", "duplicate"));
        assertTrue((Boolean) applied.get("ok"));
        assertEquals("RF-1", ((Map<?, ?>) applied.get("refund")).get("refund_no"));

        when(refundService.apply(user, "", "")).thenThrow(new IllegalArgumentException("invalid order"));
        assertEquals("invalid order", controller.apply(Map.of()).get("message"));

        when(refundService.review(user, 1L, "approve", "verified")).thenReturn(refund);
        assertTrue((Boolean) controller.review(
                        1L, Map.of("action", "approve", "admin_note", "verified"))
                .get("ok"));
        when(refundService.review(user, 2L, "", ""))
                .thenThrow(new IllegalArgumentException("not found"));
        assertFalse((Boolean) controller.review(2L, Map.of()).get("ok"));
    }

    @Test
    void listingAndPendingReviewHonorOwnershipAndAdminRole() {
        when(refundService.findByUser(user, 20, 2)).thenReturn(List.of(refund));
        when(refundService.countByUser(user)).thenReturn(1L);
        Map<String, Object> mine = controller.myRefunds(20, 2);
        assertEquals(1L, mine.get("total"));
        assertEquals(1, ((List<?>) mine.get("refunds")).size());

        assertFalse((Boolean) controller.pending(20, 0).get("ok"));
        user.setAdmin(true);
        when(refundService.findPending(20, 0)).thenReturn(List.of(refund));
        assertEquals(1, controller.pending(20, 0).get("total"));
    }

    private static Refund refund() {
        User owner = new User();
        owner.setId(9L);
        Order order = new Order();
        order.setOutTradeNo("OT-1");
        order.setUser(owner);
        Refund value = new Refund();
        value.setId(1L);
        value.setRefundNo("RF-1");
        value.setOrder(order);
        value.setUser(owner);
        value.setAmount(new BigDecimal("19.90"));
        value.setReason("duplicate");
        value.setStatus("approved");
        value.setAdminNote(null);
        value.setWalletTransactionId(8L);
        value.setCreatedAt(LocalDateTime.now());
        value.setUpdatedAt(LocalDateTime.now());
        value.setReviewedAt(LocalDateTime.now());
        return value;
    }
}
