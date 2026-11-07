package com.modstore.controller;

import com.modstore.event.EventContracts;
import com.modstore.model.Order;
import com.modstore.model.User;
import com.modstore.repository.OrderRepository;
import com.modstore.service.CurrentUserService;
import com.modstore.service.WebhookDispatcher;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

@RestController
@RequestMapping("/api/webhooks/admin")
@RequiredArgsConstructor
public class WebhookAdminController {
    private final CurrentUserService currentUserService;
    private final OrderRepository orderRepository;
    private final WebhookDispatcher webhookDispatcher;

    // Keep the old URL as an alias; replay validation and dispatch have one owner.
    @PostMapping({"/replay", "/replay-legacy"})
    public Map<String, Object> replay(@RequestBody ReplayWebhookRequest body) {
        User user = currentUserService.requireCurrentUser();
        if (!user.isAdmin()) {
            return Map.of("ok", false, "message", "需要管理员权限");
        }

        String eventId = body.eventId() == null ? "" : body.eventId().trim();
        String orderNo = body.orderNo() == null ? "" : body.orderNo().trim();
        String eventType = EventContracts.canonicalName(body.eventType() == null ? "" : body.eventType().trim());
        String paidPrefix = EventContracts.PAYMENT_PAID + ":";
        if (eventId.startsWith(paidPrefix)) {
            // Historical callers identify the order through its stable payment event ID.
            orderNo = eventId.substring(paidPrefix.length()).trim();
        }
        if (orderNo.isBlank()) {
            return Map.of("ok", false, "message", "请提供 event_id 或 order_no");
        }
        if (!eventType.isBlank() && !EventContracts.PAYMENT_PAID.equals(eventType)) {
            return Map.of("ok", false, "message", "Java 支付服务仅支持重放 " + EventContracts.PAYMENT_PAID);
        }

        Order order = orderRepository.findByOutTradeNo(orderNo).orElse(null);
        if (order == null) {
            return Map.of("ok", false, "message", "订单不存在");
        }
        if (!"paid".equals(order.getStatus())) {
            return Map.of("ok", false, "message", "只有已支付订单可重放 " + EventContracts.PAYMENT_PAID);
        }
        String replayEventId = eventId.isBlank()
                ? webhookDispatcher.eventId(EventContracts.PAYMENT_PAID, orderNo)
                : eventId;
        Map<String, Object> result = webhookDispatcher.publishPaymentPaid(order, replayEventId);
        return Map.of("ok", Boolean.TRUE.equals(result.get("ok")), "result", result);
    }

    public record ReplayWebhookRequest(String event_id, String order_no, String event_type) {
        public String eventId() {
            return event_id;
        }

        public String orderNo() {
            return order_no;
        }

        public String eventType() {
            return event_type;
        }
    }
}
