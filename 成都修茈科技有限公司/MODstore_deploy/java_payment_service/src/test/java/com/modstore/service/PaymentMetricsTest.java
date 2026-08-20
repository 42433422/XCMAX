package com.modstore.service;

import static org.assertj.core.api.Assertions.assertThat;

import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import org.junit.jupiter.api.Test;

class PaymentMetricsTest {

    @Test
    void recordsNormalizedCheckoutNotifyAndWebhookDimensions() {
        SimpleMeterRegistry registry = new SimpleMeterRegistry();
        PaymentMetrics metrics = new PaymentMetrics(registry);

        metrics.recordCheckout(" Ali Pay ", true, "created");
        metrics.recordCheckout(null, false, " ");
        metrics.recordNotify("WECHAT", "SUCCESS");
        metrics.recordWebhookDelivery("payment.paid", true, 204, 1);
        metrics.recordWebhookDelivery("x".repeat(100), false, 503, 2);

        Counter successfulCheckout = registry.find("modstore_payment_checkout_total")
                .tags("channel", "ali_pay", "result", "success", "reason", "created")
                .counter();
        Counter unknownCheckout = registry.find("modstore_payment_checkout_total")
                .tags("channel", "unknown", "result", "failure", "reason", "unknown")
                .counter();
        Counter notify = registry.find("modstore_payment_notify_total")
                .tags("provider", "wechat", "result", "success")
                .counter();

        assertThat(successfulCheckout).isNotNull();
        assertThat(successfulCheckout.count()).isEqualTo(1.0);
        assertThat(unknownCheckout).isNotNull();
        assertThat(notify).isNotNull();
        assertThat(registry.find("modstore_webhook_delivery_total").counters()).hasSize(2);
    }
}
