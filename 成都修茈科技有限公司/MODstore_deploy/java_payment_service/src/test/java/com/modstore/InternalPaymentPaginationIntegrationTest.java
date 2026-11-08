package com.modstore;

import com.modstore.controller.InternalPaymentController;
import com.modstore.model.Transaction;
import com.modstore.model.User;
import com.modstore.model.Wallet;
import com.modstore.repository.TransactionRepository;
import com.modstore.repository.UserRepository;
import com.modstore.repository.WalletRepository;
import jakarta.persistence.EntityManager;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.annotation.DirtiesContext;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.transaction.annotation.Transactional;
import org.testcontainers.containers.PostgreSQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;

import java.math.BigDecimal;
import java.util.List;
import java.util.Map;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;

@Testcontainers(disabledWithoutDocker = true)
@SpringBootTest(properties = {"spring.jpa.hibernate.ddl-auto=create-drop", "spring.flyway.enabled=false"})
@DirtiesContext(classMode = DirtiesContext.ClassMode.AFTER_CLASS)
@Transactional
class InternalPaymentPaginationIntegrationTest {
    static final String secret = UUID.randomUUID().toString() + UUID.randomUUID();
    @Container static PostgreSQLContainer<?> postgres = new PostgreSQLContainer<>(
            System.getProperty("payment.test.postgres.image", "postgres:16-alpine"));

    @DynamicPropertySource static void properties(DynamicPropertyRegistry registry) {
        registry.add("spring.datasource.url", postgres::getJdbcUrl);
        registry.add("spring.datasource.username", postgres::getUsername);
        registry.add("spring.datasource.password", postgres::getPassword);
        registry.add("jwt.secret", () -> secret);
        registry.add("payment.secret-key", () -> secret);
        registry.add("spring.security.user.password", () -> secret);
        registry.add("modstore.internal-api-key", () -> secret);
    }

    @Autowired InternalPaymentController controller;
    @Autowired UserRepository users;
    @Autowired WalletRepository wallets;
    @Autowired TransactionRepository transactions;
    @Autowired JdbcTemplate jdbc;
    @Autowired EntityManager entityManager;

    @BeforeEach void setUp() {
        for (long id = 1; id <= 5; id++) {
            User user = new User();
            user.setId(id);
            user.setUsername("pagination-" + id);
            user.setPasswordHash("unused");
            users.saveAndFlush(user);
            if (id == 2) {
                Wallet wallet = new Wallet();
                wallet.setUser(user);
                wallet.setBalance(new BigDecimal("12.34"));
                wallets.saveAndFlush(wallet);
            }
            Transaction transaction = new Transaction();
            transaction.setUser(user);
            transaction.setAmount(BigDecimal.ONE);
            transaction.setTransactionType("test");
            transaction.setStatus("completed");
            transactions.saveAndFlush(transaction);
        }
        jdbc.update("UPDATE users SET created_at = TIMESTAMP '2026-01-01 00:00:00'");
        jdbc.update("UPDATE transactions SET created_at = TIMESTAMP '2026-01-01 00:00:00'");
        entityManager.clear();
    }

    @Test void walletsUseExactOffsetsAndCountOnShortAndEmptyPages() {
        assertPage(controller.wallets(secret, 2, 0), "user_id", 5, 5L, 4L);
        assertPage(controller.wallets(secret, 2, 1), "user_id", 5, 4L, 3L);
        Map<String, Object> tail = controller.wallets(secret, 2, 3);
        assertPage(tail, "user_id", 5, 2L, 1L);
        assertThat((BigDecimal) items(tail).get(0).get("balance")).isEqualByComparingTo("12.34");
        assertThat(items(tail).get(1).get("id")).isNull();
        assertThat((BigDecimal) items(tail).get(1).get("balance")).isEqualByComparingTo("0");
        assertPage(controller.wallets(secret, 2, 4), "user_id", 5, 1L);
        assertPage(controller.wallets(secret, 2, 8), "user_id", 5);
        assertPage(controller.wallets(secret, 0, -1), "user_id", 5, 5L);
        assertPage(controller.wallets(secret, 501, 3), "user_id", 5, 2L, 1L);
    }

    @Test void transactionsUseExactOffsetsAndCountOnShortAndEmptyPages() {
        List<Long> ids = transactions.findAll().stream().map(Transaction::getId).sorted(java.util.Comparator.reverseOrder()).toList();
        assertPage(controller.transactions(secret, 2, 0), "id", 5, ids.get(0), ids.get(1));
        assertPage(controller.transactions(secret, 2, 1), "id", 5, ids.get(1), ids.get(2));
        assertPage(controller.transactions(secret, 2, 3), "id", 5, ids.get(3), ids.get(4));
        assertPage(controller.transactions(secret, 2, 4), "id", 5, ids.get(4));
        assertPage(controller.transactions(secret, 2, 8), "id", 5);
        assertPage(controller.transactions(secret, 0, -1), "id", 5, ids.get(0));
        assertPage(controller.transactions(secret, 501, 3), "id", 5, ids.get(3), ids.get(4));
    }

    @SuppressWarnings("unchecked")
    private static List<Map<String, Object>> items(Map<String, Object> page) {
        return (List<Map<String, Object>>) page.get("items");
    }

    private static void assertPage(Map<String, Object> page, String key, long total, Long... ids) {
        assertThat(page.get("total")).isEqualTo(total);
        assertThat(items(page)).extracting(row -> row.get(key)).containsExactly((Object[]) ids);
    }
}
