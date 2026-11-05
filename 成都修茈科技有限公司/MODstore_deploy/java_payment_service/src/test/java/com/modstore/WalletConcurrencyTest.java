package com.modstore;

import com.modstore.model.User;
import com.modstore.model.WalletHold;
import com.modstore.repository.UserRepository;
import com.modstore.repository.WalletHoldRepository;
import com.modstore.service.AccountLevelService;
import com.modstore.service.WalletService;
import jakarta.persistence.EntityManager;
import jakarta.persistence.PersistenceContext;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.context.bean.override.mockito.MockitoSpyBean;
import org.testcontainers.containers.PostgreSQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;

import java.math.BigDecimal;
import java.util.concurrent.*;
import java.util.Optional;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.doAnswer;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@Testcontainers(disabledWithoutDocker = true)
@SpringBootTest(properties = {"spring.jpa.hibernate.ddl-auto=create-drop", "spring.flyway.enabled=false"})
@AutoConfigureMockMvc
class WalletConcurrencyTest {
    static final String syntheticSecret = UUID.randomUUID().toString() + UUID.randomUUID();
    @Container static PostgreSQLContainer<?> postgres = new PostgreSQLContainer<>(
            System.getProperty("payment.test.postgres.image", "postgres:16-alpine"));
    @DynamicPropertySource static void properties(DynamicPropertyRegistry registry) {
        registry.add("spring.datasource.url", postgres::getJdbcUrl);
        registry.add("spring.datasource.username", postgres::getUsername);
        registry.add("spring.datasource.password", postgres::getPassword);
        registry.add("jwt.secret", () -> syntheticSecret);
        registry.add("payment.secret-key", () -> syntheticSecret);
        registry.add("spring.security.user.password", () -> syntheticSecret);
    }

    @Autowired UserRepository users;
    @Autowired WalletService wallet;
    @Autowired MockMvc http;
    @MockitoSpyBean WalletHoldRepository holds;
    @MockitoBean AccountLevelService accountLevel;
    @PersistenceContext EntityManager entityManager;

    @Test
    void serviceWalletEndpointsAreUnavailableByDefault() throws Exception {
        http.perform(post("/api/internal/llm-wallet/preauthorize").contentType("application/json").content("{}"))
                .andExpect(status().isNotFound());
    }


    @Test
    void simultaneousSettlementAndReleaseCannotBothRefund() throws Exception {
        User user = new User();
        user.setId(820001L);
        user.setUsername("synthetic-concurrency");
        user.setPasswordHash("unused");
        user = users.saveAndFlush(user);
        wallet.addBalance(user, new BigDecimal("100.00"), "synthetic", "test");
        WalletHold hold = wallet.preauthorizeAiUsage(user, new BigDecimal("5.00"),
                "synthetic", "model", "request", "preauth-concurrency");
        CyclicBarrier bothRead = new CyclicBarrier(2);
        doAnswer(invocation -> {
            Optional<WalletHold> result = entityManager.createQuery(
                    "select h from WalletHold h where h.holdNo = :number", WalletHold.class)
                    .setParameter("number", invocation.getArgument(0)).getResultStream().findFirst();
            bothRead.await(10, TimeUnit.SECONDS);
            return result;
        }).when(holds).findByHoldNo(anyString());
        final User account = user;
        ExecutorService pool = Executors.newFixedThreadPool(2);
        try {
            Future<?> a = pool.submit(() -> wallet.settleAiUsage(account, hold.getHoldNo(),
                    new BigDecimal("2.00"), "settle-concurrency"));
            Future<?> b = pool.submit(() -> wallet.releaseAiUsage(account, hold.getHoldNo(),
                    "synthetic", "release-concurrency"));
            for (Future<?> f : new Future<?>[]{a, b}) {
                try { f.get(20, TimeUnit.SECONDS); }
                catch (ExecutionException error) {
                    assertThat(error.getCause()).isInstanceOf(IllegalStateException.class)
                            .hasMessageContaining("预授权已释放");
                }
            }
            BigDecimal balance = wallet.getBalance(user);
            assertThat(balance.compareTo(new BigDecimal("98.00")) == 0
                    || balance.compareTo(new BigDecimal("100.00")) == 0).isTrue();
        } finally {
            pool.shutdownNow();
        }
    }
}
