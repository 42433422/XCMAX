package com.modstore.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.modstore.event.EventContracts;
import com.modstore.model.Order;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.Duration;
import java.time.Instant;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.Map;

@Slf4j
@Service
@RequiredArgsConstructor
public class WebhookDispatcher {

    private final ObjectMapper objectMapper;
    private final PaymentMetrics paymentMetrics;

    @Value("${webhook.url:}")
    private String webhookUrl;

    @Value("${webhook.secret:}")
    private String webhookSecret;

    @Value("${webhook.timeout-seconds:5}")
    private int timeoutSeconds;

    @Value("${webhook.retries:2}")
    private int retries;

    private final HttpClient httpClient = HttpClient.newBuilder()
            .connectTimeout(Duration.ofSeconds(5))
            .build();

    public Map<String, Object> publishPaymentPaid(Order order) {
        return publishPaymentPaid(order, eventId(EventContracts.PAYMENT_PAID, order.getOutTradeNo()));
    }

    public Map<String, Object> publishPaymentPaid(Order order, String eventId) {
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("out_trade_no", order.getOutTradeNo());
        data.put("trade_no", order.getTradeNo());
        data.put("buyer_id", order.getBuyerId());
        data.put("user_id", order.getUser().getId());
        data.put("subject", order.getSubject());
        data.put("total_amount", order.getTotalAmount() == null ? "0.00" : order.getTotalAmount().toPlainString());
        data.put("order_kind", order.getOrderKind());
        data.put("item_id", order.getItemId() == null ? 0 : order.getItemId());
        data.put("plan_id", order.getPlanId() == null ? "" : order.getPlanId());
        data.put("paid_at", order.getPaidAt());
        Map<String, Object> event = buildEvent(EventContracts.PAYMENT_PAID, order.getOutTradeNo(), data, eventId);
        return dispatch(event);
    }

    public String eventId(String eventType, String aggregateId) {
        eventType = EventContracts.canonicalName(eventType);
        String aggregate = aggregateId == null ? "" : aggregateId.trim();
        if (!aggregate.isBlank()) {
            return eventType + ":" + aggregate;
        }
        return eventType + ":" + sha256(eventType + ":" + System.nanoTime()).substring(0, 16);
    }

    private Map<String, Object> buildEvent(String eventType, String aggregateId, Map<String, Object> data, String eventId) {
        eventType = EventContracts.canonicalName(eventType);
        Map<String, Object> event = new LinkedHashMap<>();
        event.put("id", eventId);
        event.put("type", eventType);
        event.put("version", EventContracts.version(eventType));
        event.put("source", "modstore-java-payment");
        event.put("aggregate_id", aggregateId);
        event.put("created_at", Instant.now().getEpochSecond());
        event.put("data", data);
        return event;
    }

    private Map<String, Object> dispatch(Map<String, Object> event) {
        String url = webhookUrl == null ? "" : webhookUrl.trim();
        if (url.isBlank()) {
            paymentMetrics.recordWebhookDelivery(String.valueOf(event.get("type")), false, 0, 0);
            return Map.of("ok", false, "skipped", true, "message", "MODSTORE_WEBHOOK_URL is not configured");
        }
        String eventId = String.valueOf(event.get("id"));
        String eventType = String.valueOf(event.get("type"));
        try {
            objectMapper.findAndRegisterModules();
            byte[] body = objectMapper.writeValueAsBytes(event);
            String timestamp = String.valueOf(Instant.now().getEpochSecond());
            HttpRequest.Builder builder = HttpRequest.newBuilder()
                    .uri(URI.create(url))
                    .timeout(Duration.ofSeconds(Math.max(1, timeoutSeconds)))
                    .header("Content-Type", "application/json")
                    .header("X-Modstore-Webhook-Id", eventId)
                    .header("X-Modstore-Webhook-Event", String.valueOf(event.get("type")))
                    .header("X-Modstore-Webhook-Timestamp", timestamp)
                    .POST(HttpRequest.BodyPublishers.ofByteArray(body));
            if (webhookSecret != null && !webhookSecret.isBlank()) {
                builder.header("X-Modstore-Webhook-Signature", "sha256=" + hmac(timestamp, eventId, body));
            }
            int attempts = Math.max(0, Math.min(5, retries)) + 1;
            String lastError = "";
            for (int attempt = 1; attempt <= attempts; attempt++) {
                try {
                    HttpResponse<String> response = httpClient.send(builder.build(), HttpResponse.BodyHandlers.ofString());
                    boolean ok = response.statusCode() >= 200 && response.statusCode() < 300;
                    Map<String, Object> result = new LinkedHashMap<>();
                    result.put("ok", ok);
                    result.put("status_code", response.statusCode());
                    result.put("attempts", attempt);
                    result.put("body", response.body() == null ? "" : response.body().substring(0, Math.min(1000, response.body().length())));
                    paymentMetrics.recordWebhookDelivery(eventType, ok, response.statusCode(), attempt);
                    if (ok) {
                        return result;
                    }
                    lastError = "HTTP " + response.statusCode();
                } catch (Exception e) {
                    lastError = e.getMessage();
                    paymentMetrics.recordWebhookDelivery(eventType, false, 0, attempt);
                    log.warn("business webhook delivery failed event={} attempt={} error={}", eventId, attempt, e.getMessage());
                }
                if (attempt < attempts) {
                    Thread.sleep(Math.min(2000L, 250L * attempt));
                }
            }
            return Map.of("ok", false, "attempts", attempts, "message", lastError);
        } catch (Exception e) {
            log.warn("business webhook dispatch failed event={} error={}", eventId, e.getMessage());
            paymentMetrics.recordWebhookDelivery(eventType, false, 0, 0);
            return Map.of("ok", false, "message", e.getMessage());
        }
    }

    private String hmac(String timestamp, String eventId, byte[] body) throws Exception {
        Mac mac = Mac.getInstance("HmacSHA256");
        mac.init(new SecretKeySpec(webhookSecret.getBytes(StandardCharsets.UTF_8), "HmacSHA256"));
        mac.update(timestamp.getBytes(StandardCharsets.UTF_8));
        mac.update((byte) '.');
        mac.update(eventId.getBytes(StandardCharsets.UTF_8));
        mac.update((byte) '.');
        mac.update(body);
        return HexFormat.of().formatHex(mac.doFinal());
    }

    private String sha256(String value) {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            return HexFormat.of().formatHex(digest.digest(value.getBytes(StandardCharsets.UTF_8)));
        } catch (Exception e) {
            throw new IllegalStateException(e);
        }
    }
}
