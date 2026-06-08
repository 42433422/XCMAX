package com.modstore.controller;

import com.modstore.model.Order;
import com.modstore.model.User;
import com.modstore.service.CurrentUserService;
import com.modstore.service.OrderService;
import com.modstore.service.WebhookDispatcher;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;
import java.util.Optional;

@RestController
@RequestMapping("/api/webhooks")
@RequiredArgsConstructor
public class WebhookController {

    private final CurrentUserService currentUserService;
    private final OrderService orderService;
    private final WebhookDispatcher webhookDispatcher;

    @PostMapping("/admin/replay-legacy")
    public Map<String, Object> replay(@RequestBody Map<String, Object> body) {
        User user = currentUserService.requireCurrentUser();
        if (!user.isAdmin()) {
            return Map.of("ok", false, "message", "需要管理员权限");
        }

        String eventId = String.valueOf(body.getOrDefault("event_id", "")).trim();
        String orderNo = String.valueOf(body.getOrDefault("order_no", "")).trim();
        if (!eventId.isBlank() && eventId.startsWith("payment.paid:")) {
            orderNo = eventId.substring("payment.paid:".length());
        }
        if (orderNo.isBlank()) {
            return Map.of("ok", false, "message", "请提供 event_id 或 order_no");
        }
        Optional<Order> order = orderService.findByOutTradeNo(orderNo);
        if (order.isEmpty()) {
            return Map.of("ok", false, "message", "订单不存在");
        }
        if (!"paid".equals(order.get().getStatus())) {
            return Map.of("ok", false, "message", "只有已支付订单可重放 payment.paid");
        }
        String replayEventId = eventId.isBlank()
                ? webhookDispatcher.eventId("payment.paid", orderNo)
                : eventId;
        Map<String, Object> result = webhookDispatcher.publishPaymentPaid(order.get(), replayEventId);
        return Map.of("ok", Boolean.TRUE.equals(result.get("ok")), "result", result);
    }
}
