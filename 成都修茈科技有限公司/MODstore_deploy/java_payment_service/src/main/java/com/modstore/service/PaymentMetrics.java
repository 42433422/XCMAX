package com.modstore.service;

import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.MeterRegistry;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

@Service
@RequiredArgsConstructor
public class PaymentMetrics {

    private final MeterRegistry meterRegistry;

    public void recordCheckout(String channel, boolean ok, String reason) {
        Counter.builder("modstore_payment_checkout_total")
                .description("Payment checkout attempts by channel and result.")
                .tag("channel", normalize(channel))
                .tag("result", ok ? "success" : "failure")
                .tag("reason", normalize(reason))
                .register(meterRegistry)
                .increment();
    }

    public void recordNotify(String provider, String result) {
        Counter.builder("modstore_payment_notify_total")
                .description("Payment provider notification handling results.")
                .tag("provider", normalize(provider))
                .tag("result", normalize(result))
                .register(meterRegistry)
                .increment();
    }

    public void recordWebhookDelivery(String eventType, boolean ok, int statusCode, int attempt) {
        Counter.builder("modstore_webhook_delivery_total")
                .description("Business webhook delivery attempts.")
                .tag("event_type", normalize(eventType))
                .tag("result", ok ? "success" : "failure")
                .tag("status", String.valueOf(statusCode))
                .tag("attempt", String.valueOf(attempt))
                .register(meterRegistry)
                .increment();
    }

    private String normalize(String value) {
        if (value == null || value.isBlank()) {
            return "unknown";
        }
        String normalized = value.trim().toLowerCase().replaceAll("[^a-z0-9_.-]", "_");
        return normalized.length() > 64 ? normalized.substring(0, 64) : normalized;
    }
}
