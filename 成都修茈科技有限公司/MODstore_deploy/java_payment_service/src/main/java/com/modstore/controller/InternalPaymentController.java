package com.modstore.controller;

import com.modstore.model.Order;
import com.modstore.model.User;
import com.modstore.repository.UserRepository;
import com.modstore.service.OrderService;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * Service-to-service payment reads for CS/CRM (FHD 客服到款核对).
 * Not exposed to browsers; requires {@code X-Internal-Api-Key}.
 */
@RestController
@RequestMapping("/api/internal/payment")
@RequiredArgsConstructor
public class InternalPaymentController {

    private final UserRepository userRepository;
    private final OrderService orderService;

    @Value("${modstore.internal-api-key:}")
    private String internalApiKey;

    @GetMapping("/user-orders")
    public Map<String, Object> userOrders(
            @RequestHeader(value = "X-Internal-Api-Key", required = false) String key,
            @RequestParam(name = "user_id") long userId,
            @RequestParam(required = false) String status,
            @RequestParam(defaultValue = "50") int limit,
            @RequestParam(defaultValue = "0") int offset
    ) {
        requireInternalKey(key);
        User user = userRepository.findById(userId)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "user not found"));
        String normalized = normalizeStatus(status);
        int safeLimit = Math.min(Math.max(limit, 1), 100);
        int safeOffset = Math.max(offset, 0);
        List<Order> orders = orderService.findByUser(user, normalized, safeLimit, safeOffset);
        long total = orderService.countByUser(user, normalized);
        List<Map<String, Object>> rows = orders.stream().map(this::orderToMap).toList();
        return Map.of(
                "ok", true,
                "source", "java_postgresql",
                "user_id", userId,
                "orders", rows,
                "total", total
        );
    }

    private void requireInternalKey(String key) {
        String expected = internalApiKey == null ? "" : internalApiKey.trim();
        if (expected.isEmpty()) {
            throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "internal api not configured");
        }
        String got = key == null ? "" : key.trim();
        if (!expected.equals(got)) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, "invalid internal api key");
        }
    }

    private static String normalizeStatus(String status) {
        if (status == null || status.isBlank()) {
            return null;
        }
        return status.trim().toLowerCase();
    }

    private Map<String, Object> orderToMap(Order order) {
        Map<String, Object> row = new HashMap<>();
        row.put("out_trade_no", order.getOutTradeNo());
        row.put("trade_no", order.getTradeNo());
        row.put("status", order.getStatus());
        row.put("subject", order.getSubject());
        row.put("total_amount", order.getTotalAmount() == null ? "0.00" : order.getTotalAmount().toPlainString());
        row.put("order_kind", order.getOrderKind());
        row.put("plan_id", order.getPlanId() == null ? "" : order.getPlanId());
        row.put("item_id", order.getItemId() == null ? 0 : order.getItemId());
        row.put("paid_at", order.getPaidAt());
        row.put("created_at", order.getCreatedAt());
        row.put("pay_type", order.getPayType());
        row.put("fulfilled", order.isFulfilled());
        return row;
    }
}
