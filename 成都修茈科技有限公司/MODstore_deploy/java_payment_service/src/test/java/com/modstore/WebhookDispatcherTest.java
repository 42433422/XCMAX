package com.modstore;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.modstore.model.Order;
import com.modstore.model.User;
import com.modstore.service.PaymentMetrics;
import com.modstore.service.WebhookDispatcher;
import com.sun.net.httpserver.HttpServer;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;

import java.math.BigDecimal;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.time.LocalDateTime;
import java.util.Map;
import java.util.concurrent.atomic.AtomicReference;

import static org.assertj.core.api.Assertions.assertThat;

class WebhookDispatcherTest {

    @Test
    void disabledWebhookStillBuildsNullablePayloadAndStableEventIds() {
        PaymentMetrics metrics = new PaymentMetrics(new SimpleMeterRegistry());
        WebhookDispatcher dispatcher = new WebhookDispatcher(new ObjectMapper(), metrics);
        ReflectionTestUtils.setField(dispatcher, "webhookUrl", null);
        ReflectionTestUtils.setField(dispatcher, "webhookSecret", null);

        Order sparse = order();
        sparse.setTotalAmount(null);
        sparse.setItemId(42L);
        sparse.setPlanId("plan_basic");
        Map<String, Object> result = dispatcher.publishPaymentPaid(sparse, "event-1");

        assertThat(result.get("ok")).isEqualTo(false);
        assertThat(result.get("skipped")).isEqualTo(true);
        assertThat(dispatcher.eventId("payment.paid", null)).startsWith("payment.paid:");
        assertThat(dispatcher.eventId("payment.paid", "  ")).startsWith("payment.paid:");
    }

    @Test
    void failedWebhookRetriesWithoutSignatureAndReportsFinalAttempt() throws Exception {
        HttpServer server = HttpServer.create(new InetSocketAddress(0), 0);
        server.createContext("/hook", exchange -> {
            byte[] response = "retry".getBytes(StandardCharsets.UTF_8);
            exchange.sendResponseHeaders(503, response.length);
            exchange.getResponseBody().write(response);
            exchange.close();
        });
        server.start();
        try {
            WebhookDispatcher dispatcher =
                    new WebhookDispatcher(new ObjectMapper(), new PaymentMetrics(new SimpleMeterRegistry()));
            ReflectionTestUtils.setField(
                    dispatcher,
                    "webhookUrl",
                    "http://127.0.0.1:" + server.getAddress().getPort() + "/hook");
            ReflectionTestUtils.setField(dispatcher, "webhookSecret", " ");
            ReflectionTestUtils.setField(dispatcher, "timeoutSeconds", 0);
            ReflectionTestUtils.setField(dispatcher, "retries", 1);

            Map<String, Object> result = dispatcher.publishPaymentPaid(order(), "event-retry");

            assertThat(result.get("ok")).isEqualTo(false);
            assertThat(result.get("attempts")).isEqualTo(2);
            assertThat(result.get("message")).isEqualTo("HTTP 503");
        } finally {
            server.stop(0);
        }
    }

    @Test
    void paymentPaidWebhookPostsSignedEvent() throws Exception {
        AtomicReference<String> signature = new AtomicReference<>("");
        AtomicReference<String> eventType = new AtomicReference<>("");
        HttpServer server = HttpServer.create(new InetSocketAddress(0), 0);
        server.createContext("/hook", exchange -> {
            signature.set(exchange.getRequestHeaders().getFirst("X-Modstore-Webhook-Signature"));
            eventType.set(exchange.getRequestHeaders().getFirst("X-Modstore-Webhook-Event"));
            byte[] response = "ok".getBytes(StandardCharsets.UTF_8);
            exchange.sendResponseHeaders(200, response.length);
            exchange.getResponseBody().write(response);
            exchange.close();
        });
        server.start();
        try {
            WebhookDispatcher dispatcher =
                    new WebhookDispatcher(new ObjectMapper(), new PaymentMetrics(new SimpleMeterRegistry()));
            ReflectionTestUtils.setField(dispatcher, "webhookUrl", "http://127.0.0.1:" + server.getAddress().getPort() + "/hook");
            ReflectionTestUtils.setField(dispatcher, "webhookSecret", "secret");
            ReflectionTestUtils.setField(dispatcher, "timeoutSeconds", 2);
            ReflectionTestUtils.setField(dispatcher, "retries", 0);

            Map<String, Object> result = dispatcher.publishPaymentPaid(order());
            assertThat(result.get("ok")).isEqualTo(true);
            assertThat(eventType.get()).isEqualTo("payment.paid");
            assertThat(signature.get()).startsWith("sha256=");
        } finally {
            server.stop(0);
        }
    }

    private Order order() {
        User user = new User();
        user.setId(7L);
        user.setUsername("webhook-user");
        Order order = new Order();
        order.setUser(user);
        order.setOutTradeNo("MOD-WEBHOOK-1");
        order.setTradeNo("TRADE-1");
        order.setSubject("subject");
        order.setTotalAmount(new BigDecimal("12.34"));
        order.setOrderKind("wallet");
        order.setStatus("paid");
        order.setPaidAt(LocalDateTime.now());
        return order;
    }
}
