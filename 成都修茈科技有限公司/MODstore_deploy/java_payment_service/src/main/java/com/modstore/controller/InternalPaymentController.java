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

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.LocalDateTime;
import java.time.ZoneId;
import java.time.ZoneOffset;
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

    private static final ZoneId BUSINESS_ZONE = ZoneId.of("Asia/Shanghai");

    private final UserRepository userRepository;
    private final OrderService orderService;

    @Value("${modstore.internal-api-key:}")
    private String internalApiKey;

    @Value("${modstore.deploy-tier:local}")
    private String deployTier;

    @Value("${alipay.debug:false}")
    private boolean alipayDebug;

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

    /**
     * Minimal, paged payment proof for the founder customer-value ledger.
     *
     * No user id, buyer id, wallet balance or credential crosses this service
     * boundary. A row is emitted only after the Java-owned order reached
     * {@code paid}; the existing provider transaction id and payment channel
     * are retained so the Python side can continue to fail closed.
     */
    @GetMapping("/value-evidence")
    public Map<String, Object> valueEvidence(
            @RequestHeader(value = "X-Internal-Api-Key", required = false) String key,
            @RequestParam(name = "window_days", defaultValue = "90") int windowDays,
            @RequestParam(defaultValue = "1000") int limit,
            @RequestParam(defaultValue = "0") int offset
    ) {
        requireInternalKey(key);
        int safeDays = Math.min(Math.max(windowDays, 1), 3650);
        int safeLimit = Math.min(Math.max(limit, 1), 1000);
        int safeOffset = Math.max(offset, 0);
        LocalDateTime since = LocalDateTime.now(BUSINESS_ZONE).minusDays(safeDays);
        List<Order> orders = orderService.findPaidValueEvidenceSince(
                since,
                safeLimit,
                safeOffset
        );
        long total = orderService.countPaidValueEvidenceSince(since);
        List<Map<String, Object>> rows = orders.stream()
                .map(this::orderToValueEvidenceMap)
                .toList();
        return Map.of(
                "ok", true,
                "source", "java_postgresql",
                "environment", normalizedDeployTier(),
                "window_days", safeDays,
                "limit", safeLimit,
                "offset", safeOffset,
                "total", total,
                "orders", rows
        );
    }

    private void requireInternalKey(String key) {
        String expected = internalApiKey == null ? "" : internalApiKey.trim();
        if (expected.isEmpty()) {
            throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "internal api not configured");
        }
        String got = key == null ? "" : key.trim();
        if (!MessageDigest.isEqual(
                expected.getBytes(StandardCharsets.UTF_8),
                got.getBytes(StandardCharsets.UTF_8)
        )) {
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

    private Map<String, Object> orderToValueEvidenceMap(Order order) {
        Map<String, Object> row = new HashMap<>();
        Map<String, Object> fulfillment = orderService.getCustomerValueFulfillmentEvidence(order);
        String payType = order.getPayType() == null ? "" : order.getPayType().trim().toLowerCase();
        String provider = payType.contains("wechat") ? "wechat" :
                (payType.contains("alipay") || "page".equals(payType) ? "alipay" : "");
        boolean refunded = order.getRefundStatus() != null
                && !order.getRefundStatus().isBlank()
                && !"none".equalsIgnoreCase(order.getRefundStatus());
        row.put("out_trade_no", order.getOutTradeNo());
        row.put("status", order.getStatus());
        row.put("subject", order.getSubject());
        row.put("order_kind", order.getOrderKind() == null ? "" : order.getOrderKind());
        row.put("plan_id", order.getPlanId() == null ? "" : order.getPlanId());
        row.put("item_id", order.getItemId() == null ? 0 : order.getItemId());
        row.put(
                "total_amount",
                order.getTotalAmount() == null ? "0.00" : order.getTotalAmount().toPlainString()
        );
        row.put("paid_at", toUtcTimestamp(order.getPaidAt()));
        row.put("payment_provider", provider);
        row.put("provider_trade_no", order.getTradeNo() == null ? "" : order.getTradeNo());
        row.put("provider_verification", "java_gateway_verified");
        row.put("provider_test_mode", alipayDebug);
        row.put("payment_environment", normalizedDeployTier());
        row.put("refund_status", order.getRefundStatus() == null ? "none" : order.getRefundStatus());
        row.put("refunded", refunded);
        row.put("fulfilled", order.isFulfilled());
        row.put("fulfillment_verified", Boolean.TRUE.equals(fulfillment.get("verified")));
        row.put("fulfillment_reason", String.valueOf(fulfillment.getOrDefault("reason", "")));
        row.put("fulfillment_artifact_id", String.valueOf(fulfillment.getOrDefault("artifact_id", "")));
        row.put(
                "fulfillment_artifact_sha256",
                String.valueOf(fulfillment.getOrDefault("artifact_sha256", ""))
        );
        Object fulfilledAt = fulfillment.get("fulfilled_at");
        row.put(
                "fulfilled_at",
                fulfilledAt instanceof LocalDateTime ? toUtcTimestamp((LocalDateTime) fulfilledAt) : ""
        );
        return row;
    }

    private String normalizedDeployTier() {
        return deployTier == null ? "local" : deployTier.trim().toLowerCase();
    }

    private static String toUtcTimestamp(LocalDateTime value) {
        if (value == null) {
            return "";
        }
        return value.atZone(BUSINESS_ZONE).withZoneSameInstant(ZoneOffset.UTC).toInstant().toString();
    }
}
