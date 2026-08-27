package com.modstore.controller;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.modstore.model.Order;
import com.modstore.model.Refund;
import com.modstore.model.User;
import com.modstore.service.CurrentUserService;
import com.modstore.service.OrderService;
import com.modstore.service.RefundService;
import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;

class AdminCommerceControllerTest {

    private OrderService orderService;
    private RefundService refundService;
    private CurrentUserService currentUserService;
    private AdminCommerceController controller;
    private User admin;

    @BeforeEach
    void setUp() {
        orderService = mock(OrderService.class);
        refundService = mock(RefundService.class);
        currentUserService = mock(CurrentUserService.class);
        controller = new AdminCommerceController(orderService, refundService, currentUserService);
        ReflectionTestUtils.setField(controller, "publicOrigin", "https://admin.example.test/");
        ReflectionTestUtils.setField(controller, "marketPrefix", "/market/");
        admin = user(99L, true);
        when(currentUserService.requireCurrentUser()).thenReturn(admin);
    }

    @Test
    void listingReturnsRowsAndCommercialSummary() {
        Order paid = order("OT-PAID", "paid", "19.90");
        Order pending = order("OT-PENDING", "pending", "10.00");
        Order unknown = order("OT-UNKNOWN", null, "8.00");
        when(orderService.findAllForAdmin(admin, "paid", 10, 0)).thenReturn(List.of(paid));
        when(orderService.findAllForAdmin(admin, null, 500, 0))
                .thenReturn(List.of(paid, pending, unknown));
        when(orderService.countAllForAdmin(admin, "paid")).thenReturn(1L);

        Map<String, Object> result = controller.orders("paid", 10, 0);

        assertThat(result.get("total")).isEqualTo(1L);
        assertThat(result.get("source")).isEqualTo("java_postgresql");
        assertThat((List<?>) result.get("items")).hasSize(1);
        Map<?, ?> summary = (Map<?, ?>) result.get("summary");
        assertThat(summary.get("total_orders")).isEqualTo(3);
        assertThat(summary.get("paid_orders")).isEqualTo(1);
        assertThat(summary.get("pending_orders")).isEqualTo(1);
        assertThat(summary.get("paid_revenue")).isEqualTo(new BigDecimal("19.90"));
        Map<?, ?> byStatus = (Map<?, ?>) summary.get("by_status");
        assertThat(byStatus.get("paid")).isEqualTo(1);
        assertThat(byStatus.get("pending")).isEqualTo(1);
        assertThat(byStatus.get("unknown")).isEqualTo(1);
    }

    @Test
    void cancelRepriceAndRefundRequestDelegateWithAuditableReason() {
        Order cancelled = order("OT-CANCEL", "closed", "10.00");
        when(orderService.cancelPendingOrderAsAdmin(admin, "OT-CANCEL", "客户确认取消"))
                .thenReturn(cancelled);
        Map<String, Object> cancel = controller.cancel(
                "OT-CANCEL", Map.of("reason", "客户确认取消"));
        assertThat(cancel).containsEntry("ok", true).containsEntry("status", "closed");

        Order replacement = order("OT-ADJ", "pending", "8.00");
        Map<String, Object> repriced = new HashMap<>();
        repriced.put("ok", true);
        repriced.put("replacement_order", replacement);
        when(orderService.repricePendingOrderAsAdmin(
                        admin,
                        "OT-ORIGINAL",
                        new BigDecimal("8.00"),
                        "合同金额调整",
                        "https://admin.example.test/market/payment/return"))
                .thenReturn(repriced);
        Map<String, Object> reprice = controller.reprice(
                "OT-ORIGINAL",
                Map.of("new_amount", "8.00", "reason", "合同金额调整"));
        Map<?, ?> replacementPayload = (Map<?, ?>) reprice.get("replacement_order");
        assertThat(replacementPayload.get("out_trade_no")).isEqualTo("OT-ADJ");
        assertThat(replacementPayload.get("status")).isEqualTo("pending");

        Refund refund = new Refund();
        refund.setId(7L);
        refund.setStatus("pending");
        when(refundService.applyForAdmin(admin, "OT-PAID", "客户确认退款"))
                .thenReturn(refund);
        assertThat(controller.refundRequest(
                        "OT-PAID", Map.of("reason", "客户确认退款")))
                .containsEntry("ok", true)
                .containsEntry("refund_id", 7L)
                .containsEntry("status", "pending");
        verify(refundService).applyForAdmin(admin, "OT-PAID", "客户确认退款");
    }

    @Test
    void authorityReasonAndConflictFailuresAreExplicit() {
        admin.setAdmin(false);
        assertThatThrownBy(() -> controller.orders(null, 10, 0))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessage("需要管理员权限");

        admin.setAdmin(true);
        assertThatThrownBy(() -> controller.cancel("OT-1", Map.of("reason", "短")))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessage("操作原因至少 4 个字");
        assertThat(controller.handleBusinessConflict(new IllegalArgumentException("业务冲突"))
                        .getBody())
                .containsEntry("ok", false)
                .containsEntry("message", "业务冲突");
        assertThat(controller.handleBusinessConflict(new IllegalArgumentException()).getBody())
                .containsEntry("message", "订单状态不允许当前操作");
    }

    private static User user(long id, boolean admin) {
        User value = new User();
        value.setId(id);
        value.setUsername("admin");
        value.setPasswordHash("hash");
        value.setAdmin(admin);
        return value;
    }

    private static Order order(String orderNo, String status, String amount) {
        Order value = new Order();
        value.setId(1L);
        value.setOutTradeNo(orderNo);
        value.setSubject("测试订单");
        value.setTotalAmount(new BigDecimal(amount));
        value.setUser(user(1L, false));
        value.setOrderKind("plan");
        value.setPlanId("plan_pro");
        value.setStatus(status);
        value.setPayType("alipay_page");
        value.setCreatedAt(LocalDateTime.now());
        value.setUpdatedAt(LocalDateTime.now());
        return value;
    }
}
