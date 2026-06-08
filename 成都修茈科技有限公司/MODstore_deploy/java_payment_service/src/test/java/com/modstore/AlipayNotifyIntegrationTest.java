package com.modstore;

import com.modstore.model.Order;
import com.modstore.model.User;
import com.modstore.model.Wallet;
import com.modstore.repository.OrderRepository;
import com.modstore.repository.UserRepository;
import com.modstore.repository.WalletRepository;
import com.modstore.service.AlipayService;
import com.modstore.service.WebhookDispatcher;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.web.servlet.MockMvc;
import org.testcontainers.containers.GenericContainer;
import org.testcontainers.containers.PostgreSQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;

import java.math.BigDecimal;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyMap;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@Testcontainers(disabledWithoutDocker = true)
@SpringBootTest(properties = {
        "spring.jpa.hibernate.ddl-auto=create-drop",
        "spring.flyway.enabled=false",
        "jwt.secret=modstore-test-secret-change-me-32bytes",
        "payment.secret-key=test-payment-secret"
})
@AutoConfigureMockMvc
class AlipayNotifyIntegrationTest {

    @Container
    static PostgreSQLContainer<?> postgres = new PostgreSQLContainer<>("postgres:16-alpine")
            .withDatabaseName("payment_test")
            .withUsername("test")
            .withPassword("test");

    @Container
    static GenericContainer<?> redis = new GenericContainer<>("redis:7-alpine").withExposedPorts(6379);

    @DynamicPropertySource
    static void properties(DynamicPropertyRegistry registry) {
        registry.add("spring.datasource.url", postgres::getJdbcUrl);
        registry.add("spring.datasource.username", postgres::getUsername);
        registry.add("spring.datasource.password", postgres::getPassword);
        registry.add("spring.data.redis.url", () -> "redis://" + redis.getHost() + ":" + redis.getMappedPort(6379));
    }

    @Autowired
    MockMvc mockMvc;

    @Autowired
    UserRepository userRepository;

    @Autowired
    OrderRepository orderRepository;

    @Autowired
    WalletRepository walletRepository;

    @MockBean
    AlipayService alipayService;

    @MockBean
    WebhookDispatcher webhookDispatcher;

    User user;

    @BeforeEach
    void setUp() {
        orderRepository.deleteAll();
        walletRepository.deleteAll();
        userRepository.deleteAll();
        user = new User();
        user.setUsername("notify-user");
        user.setEmail("notify@example.com");
        user.setPasswordHash("hash");
        user.setAdmin(true);
        user = userRepository.save(user);
        when(alipayService.verifyNotify(anyMap())).thenReturn(true);
        when(webhookDispatcher.publishPaymentPaid(any(Order.class))).thenReturn(Map.of("ok", true));
    }

    @Test
    void alipayNotifyPaysWalletOrderAndDispatchesWebhook() throws Exception {
        createPendingWalletOrder("MOD-NOTIFY-1", "19.90");

        mockMvc.perform(post("/api/payment/notify/alipay")
                        .param("out_trade_no", "MOD-NOTIFY-1")
                        .param("trade_status", "TRADE_SUCCESS")
                        .param("trade_no", "TRADE-NOTIFY-1")
                        .param("buyer_id", "BUYER-1")
                        .param("total_amount", "19.90"))
                .andExpect(status().isOk())
                .andExpect(content().string("success"));

        Order paid = orderRepository.findByOutTradeNo("MOD-NOTIFY-1").orElseThrow();
        assertThat(paid.getStatus()).isEqualTo("paid");
        assertThat(paid.isFulfilled()).isTrue();
        Wallet wallet = walletRepository.findByUser(user).orElseThrow();
        assertThat(wallet.getBalance()).isEqualByComparingTo("19.90");
        verify(webhookDispatcher, times(1)).publishPaymentPaid(any(Order.class));
    }

    @Test
    void duplicateAlipayNotifyIsIdempotent() throws Exception {
        createPendingWalletOrder("MOD-NOTIFY-2", "8.00");

        for (int i = 0; i < 2; i++) {
            mockMvc.perform(post("/api/payment/notify/alipay")
                            .param("out_trade_no", "MOD-NOTIFY-2")
                            .param("trade_status", "TRADE_SUCCESS")
                            .param("trade_no", "TRADE-NOTIFY-2")
                            .param("total_amount", "8.00"))
                    .andExpect(status().isOk())
                    .andExpect(content().string("success"));
        }

        Wallet wallet = walletRepository.findByUser(user).orElseThrow();
        assertThat(wallet.getBalance()).isEqualByComparingTo("8.00");
        verify(webhookDispatcher, times(1)).publishPaymentPaid(any(Order.class));
    }

    @Test
    void amountMismatchReturnsFailAndKeepsOrderPending() throws Exception {
        createPendingWalletOrder("MOD-NOTIFY-3", "9.90");

        mockMvc.perform(post("/api/payment/notify/alipay")
                        .param("out_trade_no", "MOD-NOTIFY-3")
                        .param("trade_status", "TRADE_SUCCESS")
                        .param("trade_no", "TRADE-NOTIFY-3")
                        .param("total_amount", "8.00"))
                .andExpect(status().isOk())
                .andExpect(content().string("fail"));

        Order pending = orderRepository.findByOutTradeNo("MOD-NOTIFY-3").orElseThrow();
        assertThat(pending.getStatus()).isEqualTo("pending");
    }

    private void createPendingWalletOrder(String outTradeNo, String amount) {
        Order order = new Order();
        order.setUser(user);
        order.setOutTradeNo(outTradeNo);
        order.setSubject("wallet recharge");
        order.setTotalAmount(new BigDecimal(amount));
        order.setOrderKind("wallet");
        order.setStatus("pending");
        order.setFulfilled(false);
        orderRepository.save(order);
    }
}
