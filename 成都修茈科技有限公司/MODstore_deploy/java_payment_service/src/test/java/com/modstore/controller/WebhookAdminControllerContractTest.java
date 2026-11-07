package com.modstore.controller;

import com.modstore.event.EventContracts;
import com.modstore.model.Order;
import com.modstore.model.User;
import com.modstore.repository.OrderRepository;
import com.modstore.service.CurrentUserService;
import com.modstore.service.WebhookDispatcher;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.web.server.ResponseStatusException;

import java.util.Map;
import java.util.Optional;

import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

class WebhookAdminControllerContractTest {
    private static final String BASE = "/api/webhooks/admin";
    private CurrentUserService users;
    private OrderRepository orders;
    private WebhookDispatcher dispatcher;
    private MockMvc mvc;
    private User admin;
    private Order paid;

    @BeforeEach
    void setUp() {
        users = mock(CurrentUserService.class);
        orders = mock(OrderRepository.class);
        dispatcher = mock(WebhookDispatcher.class);
        mvc = MockMvcBuilders.standaloneSetup(
                new WebhookAdminController(users, orders, dispatcher)).build();
        admin = new User();
        admin.setAdmin(true);
        when(users.requireCurrentUser()).thenReturn(admin);
        paid = new Order();
        paid.setOutTradeNo("OT-1");
        paid.setStatus("paid");
    }

    @ParameterizedTest
    @ValueSource(strings = {"/replay", "/replay-legacy"})
    void eventIdIdentifiesOrderAndIsPreservedForIdempotency(String path) throws Exception {
        when(orders.findByOutTradeNo("OT-1")).thenReturn(Optional.of(paid));
        when(dispatcher.publishPaymentPaid(paid, "payment.paid:OT-1"))
                .thenReturn(Map.of("ok", true));

        for (String body : new String[]{
                "{\"event_id\":\" payment.paid:OT-1 \"}",
                "{\"event_id\":\"payment.paid:OT-1\",\"order_no\":\"legacy-ignored\"}"}) {
            mvc.perform(post(BASE + path).contentType(MediaType.APPLICATION_JSON).content(body))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.ok").value(true))
                    .andExpect(jsonPath("$.result.ok").value(true));
        }
        verify(orders, times(2)).findByOutTradeNo("OT-1");
        verify(dispatcher, times(2)).publishPaymentPaid(paid, "payment.paid:OT-1");
    }

    @ParameterizedTest
    @ValueSource(strings = {"/replay", "/replay-legacy"})
    void orderOnlyReplayReusesCanonicalEventId(String path) throws Exception {
        when(orders.findByOutTradeNo("OT-1")).thenReturn(Optional.of(paid));
        when(dispatcher.eventId(EventContracts.PAYMENT_PAID, "OT-1"))
                .thenReturn("payment.paid:OT-1");
        when(dispatcher.publishPaymentPaid(paid, "payment.paid:OT-1"))
                .thenReturn(Map.of("ok", true));
        for (int attempt = 0; attempt < 2; attempt++) {
            mvc.perform(post(BASE + path).contentType(MediaType.APPLICATION_JSON)
                            .content("{\"order_no\":\" OT-1 \",\"event_type\":\" payment.order_paid \"}"))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.ok").value(true));
        }
        verify(dispatcher, times(2)).publishPaymentPaid(paid, "payment.paid:OT-1");
    }

    @ParameterizedTest
    @ValueSource(strings = {"/replay", "/replay-legacy"})
    void explicitCustomIdAndDeliveryFailureArePreserved(String path) throws Exception {
        when(orders.findByOutTradeNo("OT-1")).thenReturn(Optional.of(paid));
        when(dispatcher.publishPaymentPaid(paid, "historic-event-id"))
                .thenReturn(Map.of("ok", false, "message", "HTTP 503"));
        mvc.perform(post(BASE + path).contentType(MediaType.APPLICATION_JSON)
                        .content("{\"order_no\":\"OT-1\",\"event_id\":\"historic-event-id\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.ok").value(false))
                .andExpect(jsonPath("$.result.message").value("HTTP 503"));
        verify(dispatcher).publishPaymentPaid(paid, "historic-event-id");
    }

    @ParameterizedTest
    @ValueSource(strings = {"/replay", "/replay-legacy"})
    void rejectsMissingOrderAndUnsupportedEventBeforeLookup(String path) throws Exception {
        for (String body : new String[]{"{}", "{\"event_id\":\"unknown-id\"}",
                "{\"event_id\":\"payment.paid:\"}",
                "{\"order_no\":\"OT-1\",\"event_type\":\"refund.approved\"}"}) {
            mvc.perform(post(BASE + path).contentType(MediaType.APPLICATION_JSON).content(body))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.ok").value(false));
        }
        verifyNoInteractions(orders, dispatcher);
    }

    @ParameterizedTest
    @ValueSource(strings = {"/replay", "/replay-legacy"})
    void rejectsUnknownAndUnpaidOrdersWithoutDispatch(String path) throws Exception {
        when(orders.findByOutTradeNo("OT-1")).thenReturn(Optional.empty());
        mvc.perform(post(BASE + path).contentType(MediaType.APPLICATION_JSON)
                        .content("{\"order_no\":\"OT-1\"}"))
                .andExpect(jsonPath("$.message").value("订单不存在"));
        paid.setStatus("pending");
        when(orders.findByOutTradeNo("OT-1")).thenReturn(Optional.of(paid));
        mvc.perform(post(BASE + path).contentType(MediaType.APPLICATION_JSON)
                        .content("{\"event_id\":\"payment.paid:OT-1\"}"))
                .andExpect(jsonPath("$.ok").value(false))
                .andExpect(jsonPath("$.message").value("只有已支付订单可重放 payment.paid"));
        verifyNoInteractions(dispatcher);
    }

    @ParameterizedTest
    @ValueSource(strings = {"/replay", "/replay-legacy"})
    void bothUrlsRequireAnAuthenticatedAdministrator(String path) throws Exception {
        admin.setAdmin(false);
        mvc.perform(post(BASE + path).contentType(MediaType.APPLICATION_JSON)
                        .content("{\"order_no\":\"OT-1\"}"))
                .andExpect(jsonPath("$.ok").value(false))
                .andExpect(jsonPath("$.message").value("需要管理员权限"));
        when(users.requireCurrentUser()).thenThrow(new ResponseStatusException(HttpStatus.UNAUTHORIZED));
        mvc.perform(post(BASE + path).contentType(MediaType.APPLICATION_JSON)
                        .content("{\"order_no\":\"OT-1\"}"))
                .andExpect(status().isUnauthorized());
        verifyNoInteractions(orders, dispatcher);
    }
}
