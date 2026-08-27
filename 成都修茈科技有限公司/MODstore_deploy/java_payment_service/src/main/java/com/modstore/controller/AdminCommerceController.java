package com.modstore.controller;

import com.modstore.model.Order;
import com.modstore.model.Refund;
import com.modstore.model.User;
import com.modstore.service.CurrentUserService;
import com.modstore.service.OrderService;
import com.modstore.service.RefundService;
import com.modstore.util.MoneyUtils;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.math.BigDecimal;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/api/admin/commerce")
@RequiredArgsConstructor
public class AdminCommerceController {
    private final OrderService orderService;
    private final RefundService refundService;
    private final CurrentUserService currentUserService;

    @Value("${payment.public-origin}")
    private String publicOrigin;

    @Value("${payment.market-prefix}")
    private String marketPrefix;

    @GetMapping("/orders")
    public Map<String, Object> orders(
            @RequestParam(required = false) String status,
            @RequestParam(defaultValue = "100") int limit,
            @RequestParam(defaultValue = "0") int offset
    ) {
        User admin = requireAdmin();
        List<Order> rows = orderService.findAllForAdmin(admin, status, limit, offset);
        List<Order> all = orderService.findAllForAdmin(admin, null, 500, 0);
        Map<String, Object> summary = summarize(all);
        return Map.of(
                "items", rows.stream().map(this::orderToMap).toList(),
                "total", orderService.countAllForAdmin(admin, status),
                "summary", summary,
                "source", "java_postgresql"
        );
    }

    @PostMapping("/orders/{orderNo}/cancel")
    public Map<String, Object> cancel(@PathVariable String orderNo, @RequestBody Map<String, Object> body) {
        User admin = requireAdmin();
        Order order = orderService.cancelPendingOrderAsAdmin(admin, orderNo, requiredReason(body));
        return Map.of("ok", true, "status", "closed", "order", orderToMap(order));
    }

    @PostMapping("/orders/{orderNo}/reprice")
    public Map<String, Object> reprice(@PathVariable String orderNo, @RequestBody Map<String, Object> body) {
        User admin = requireAdmin();
        BigDecimal amount = MoneyUtils.parse(body.get("new_amount"));
        String returnUrl = publicOrigin.replaceAll("/+$", "")
                + "/" + marketPrefix.replaceAll("^/+|/+$", "")
                + "/payment/return";
        Map<String, Object> result = orderService.repricePendingOrderAsAdmin(
                admin, orderNo, amount, requiredReason(body), returnUrl
        );
        Object replacement = result.get("replacement_order");
        if (replacement instanceof Order order) {
            result.put("replacement_order", orderToMap(order));
        }
        return result;
    }

    @PostMapping("/orders/{orderNo}/refund-request")
    public Map<String, Object> refundRequest(@PathVariable String orderNo, @RequestBody Map<String, Object> body) {
        User admin = requireAdmin();
        Refund refund = refundService.applyForAdmin(admin, orderNo, requiredReason(body));
        return Map.of("ok", true, "refund_id", refund.getId(), "status", refund.getStatus());
    }

    @ExceptionHandler(IllegalArgumentException.class)
    public ResponseEntity<Map<String, Object>> handleBusinessConflict(IllegalArgumentException error) {
        return ResponseEntity.status(HttpStatus.CONFLICT).body(Map.of(
                "ok", false,
                "message", error.getMessage() == null ? "订单状态不允许当前操作" : error.getMessage()
        ));
    }

    private User requireAdmin() {
        User user = currentUserService.requireCurrentUser();
        if (!user.isAdmin()) {
            throw new IllegalArgumentException("需要管理员权限");
        }
        return user;
    }

    private String requiredReason(Map<String, Object> body) {
        String reason = String.valueOf(body.getOrDefault("reason", "")).trim();
        if (reason.length() < 4) {
            throw new IllegalArgumentException("操作原因至少 4 个字");
        }
        return reason;
    }

    private Map<String, Object> orderToMap(Order order) {
        Map<String, Object> row = new HashMap<>();
        row.put("id", order.getId());
        row.put("out_trade_no", order.getOutTradeNo());
        row.put("subject", order.getSubject());
        row.put("total_amount", order.getTotalAmount());
        row.put("user_id", order.getUser().getId());
        row.put("order_kind", order.getOrderKind());
        row.put("item_id", order.getItemId());
        row.put("plan_id", order.getPlanId());
        row.put("status", order.getStatus());
        row.put("fulfilled", order.isFulfilled());
        row.put("pay_type", order.getPayType());
        row.put("refund_status", order.getRefundStatus());
        row.put("created_at", order.getCreatedAt());
        row.put("updated_at", order.getUpdatedAt());
        return row;
    }

    private Map<String, Object> summarize(List<Order> rows) {
        Map<String, Integer> byStatus = new HashMap<>();
        BigDecimal revenue = BigDecimal.ZERO;
        int paid = 0;
        int pending = 0;
        for (Order order : rows) {
            String status = order.getStatus() == null ? "unknown" : order.getStatus();
            byStatus.put(status, byStatus.getOrDefault(status, 0) + 1);
            if ("paid".equals(status)) {
                paid++;
                revenue = revenue.add(order.getTotalAmount());
            } else if ("pending".equals(status)) {
                pending++;
            }
        }
        Map<String, Object> result = new HashMap<>();
        result.put("total_orders", rows.size());
        result.put("paid_orders", paid);
        result.put("pending_orders", pending);
        result.put("paid_revenue", revenue);
        result.put("by_status", byStatus);
        return result;
    }
}
