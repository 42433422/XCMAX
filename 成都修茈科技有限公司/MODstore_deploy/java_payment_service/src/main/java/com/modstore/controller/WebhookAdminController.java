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

    @PostMapping("/replay")
    public Map<String, Object> replay(@RequestBody ReplayWebhookRequest body) {
        User user = currentUserService.requireCurrentUser();
        if (!user.isAdmin()) {
            return Map.of("ok", false, "message", "需要管理员权限");
        }

        String orderNo = body.orderNo() == null ? "" : body.orderNo().trim();
        String eventType = EventContracts.canonicalName(body.eventType() == null ? "" : body.eventType()).trim();
        if (orderNo.isBlank()) {
            return Map.of("ok", false, "message", "请提供 order_no");
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
        Map<String, Object> result = webhookDispatcher.publishPaymentPaid(order);
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
