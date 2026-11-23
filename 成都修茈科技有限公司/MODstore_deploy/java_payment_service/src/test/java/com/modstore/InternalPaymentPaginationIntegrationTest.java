package com.modstore;

import com.modstore.controller.InternalPaymentController;
import com.modstore.controller.InternalRefundEvidenceController;
import com.modstore.model.Order;
import com.modstore.model.Refund;
import com.modstore.model.Transaction;
import com.modstore.model.User;
import com.modstore.model.Wallet;
import com.modstore.repository.OrderRepository;
import com.modstore.repository.RefundRepository;
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
import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;

@Testcontainers(disabledWithoutDocker = true)
@SpringBootTest(properties = {"spring.jpa.hibernate.ddl-auto=create-drop", "spring.flyway.enabled=false",
        "modstore.deploy-tier=production", "alipay.debug=false"})
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
    @Autowired InternalRefundEvidenceController refundEvidence;
    @Autowired OrderRepository orders;
    @Autowired RefundRepository refunds;
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

    @Test void approvedRefundWithoutReviewTimeRemainsUnknownInPinnedEvidencePages() {
        LocalDateTime now = LocalDateTime.now();
        Refund known = persistRefund("approved", now.minusMinutes(2));
        Refund missingTime = persistRefund("approved", null);
        persistRefund("approved", now.minusDays(91));
        persistRefund("approved", now.plusDays(1));
        persistRefund("pending", null);
        entityManager.clear();

        Map<String, Object> first = refundEvidence.evidence(secret, 90, 1, 0, 0, "");
        assertThat(first).containsEntry("total", 2L).containsEntry("through_id", missingTime.getId())
                .containsEntry("next_after", known.getId());
        assertThat(refundRows(first)).hasSize(1);
        assertThat(refundRows(first).get(0)).containsEntry("refund_id", known.getId())
                .containsEntry("verified", true).containsEntry("amount_cents", 100L);

        // A newly observed incomplete refund belongs to the next snapshot, not this page chain.
        persistRefund("approved", null);
        entityManager.clear();
        Map<String, Object> second = refundEvidence.evidence(secret, 90, 1, known.getId(),
                missingTime.getId(), (String) first.get("as_of"));
        assertThat(second).containsEntry("total", 2L).containsEntry("through_id", missingTime.getId())
                .containsEntry("as_of", first.get("as_of")).containsEntry("next_after", null);
        assertThat(refundRows(second)).containsExactly(Map.of("refund_id", missingTime.getId(),
                "verified", false, "reason", "wallet_refund_evidence_incomplete"));
    }

    private Refund persistRefund(String status, LocalDateTime reviewedAt) {
        String identity = UUID.randomUUID().toString();
        User user = users.findById(1L).orElseThrow();
        LocalDateTime at = reviewedAt == null ? LocalDateTime.now().minusMinutes(2) : reviewedAt;
        Order order = new Order();
        order.setUser(user);
        order.setOutTradeNo("customer-order-" + identity);
        order.setTradeNo("native-trade-" + identity);
        order.setSubject("Purchased file service");
        order.setOrderKind("item");
        order.setTotalAmount(BigDecimal.ONE);
        order.setRefundedAmount(BigDecimal.ONE);
        order.setStatus("refunded");
        order.setRefundStatus("refunded");
        order.setFulfilled(true);
        order.setPaidAt(at.minusDays(1));
        order.setRefundedAt(at);
        order.setPayType("page");
        orders.saveAndFlush(order);
        Transaction credit = new Transaction();
        credit.setUser(user);
        credit.setAmount(BigDecimal.ONE);
        credit.setBalanceBefore(BigDecimal.ZERO);
        credit.setBalanceAfter(BigDecimal.ONE);
        credit.setTransactionType("wallet_refund");
        credit.setStatus("completed");
        credit.setOrderNo(order.getOutTradeNo());
        credit.setReferenceNo(order.getOutTradeNo());
        credit.setRefundNo("customer-refund-" + identity);
        credit.setIdempotencyKey("refund:wallet-credit:" + credit.getRefundNo());
        transactions.saveAndFlush(credit);
        credit.setCreatedAt(at.minusSeconds(1));
        transactions.saveAndFlush(credit);
        Refund refund = new Refund();
        refund.setRefundNo(credit.getRefundNo());
        refund.setOrder(order);
        refund.setUser(user);
        refund.setAmount(BigDecimal.ONE);
        refund.setReason("Original wallet refund evidence");
        refund.setStatus(status);
        refund.setReviewedBy(users.findById(2L).orElseThrow());
        refund.setWalletTransactionId(credit.getId());
        refund.setReviewedAt(reviewedAt);
        return refunds.saveAndFlush(refund);
    }

    @SuppressWarnings("unchecked")
    private static List<Map<String, Object>> refundRows(Map<String, Object> page) {
        return (List<Map<String, Object>>) page.get("refunds");
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
