package com.modstore;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.modstore.model.User;
import com.modstore.model.Transaction;
import com.modstore.model.WalletHold;
import com.modstore.repository.UserRepository;
import com.modstore.repository.TransactionRepository;
import com.modstore.repository.WalletHoldRepository;
import com.modstore.service.AccountLevelService;
import com.modstore.service.WalletService;
import jakarta.persistence.EntityManager;
import jakarta.persistence.PersistenceContext;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.dao.DataIntegrityViolationException;
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
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.Optional;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.eq;
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
        registry.add("modstore.internal-api-key", () -> syntheticSecret);
    }

    @Autowired UserRepository users;
    @Autowired WalletService wallet;
    @Autowired MockMvc http;
    @Autowired ObjectMapper json;
    @MockitoSpyBean WalletHoldRepository holds;
    @MockitoSpyBean TransactionRepository transactions;
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

    @Test
    void internalCreditReturnsTheCommittedReceiptAndRejectsConflictingReplay() throws Exception {
        User account = creditAccount(820006L);
        User other = creditAccount(820007L);
        String key = "synthetic-credit-http";
        byte[] request = json.writeValueAsBytes(Map.of(
                "user_id", account.getId(), "amount", "5.00", "idempotency_key", key));
        http.perform(post("/api/internal/payment/wallet/credit")
                        .header("X-Internal-Api-Key", "wrong").contentType("application/json").content(request))
                .andExpect(status().isForbidden());
        JsonNode receipt = json.readTree(http.perform(post("/api/internal/payment/wallet/credit")
                        .header("X-Internal-Api-Key", syntheticSecret).contentType("application/json").content(request))
                .andExpect(status().isOk()).andReturn().getResponse().getContentAsString());
        Transaction stored = transactions.findByIdempotencyKey(key).orElseThrow();
        assertThat(receipt.path("ok").asBoolean()).isTrue();
        assertThat(receipt.path("source").asText()).isEqualTo("java_postgresql");
        assertThat(receipt.path("transaction_id").asLong()).isEqualTo(stored.getId());
        assertThat(receipt.path("user_id").asLong()).isEqualTo(account.getId());
        assertThat(receipt.path("amount").asText()).isEqualTo("5.00");
        assertThat(receipt.path("balance").asText()).isEqualTo("5.00");
        assertThat(receipt.path("idempotency_key").asText()).isEqualTo(key);
        assertThat(receipt.path("status").asText()).isEqualTo("completed");
        JsonNode replay = json.readTree(http.perform(post("/api/internal/payment/wallet/credit")
                        .header("X-Internal-Api-Key", syntheticSecret).contentType("application/json").content(request))
                .andExpect(status().isOk()).andReturn().getResponse().getContentAsString());
        assertThat(replay).isEqualTo(receipt);
        for (Map<String, Object> conflict : List.of(
                Map.<String, Object>of("user_id", other.getId(), "amount", "5.00", "idempotency_key", key),
                Map.<String, Object>of("user_id", account.getId(), "amount", "6.00", "idempotency_key", key))) {
            http.perform(post("/api/internal/payment/wallet/credit")
                            .header("X-Internal-Api-Key", syntheticSecret).contentType("application/json")
                            .content(json.writeValueAsBytes(conflict)))
                    .andExpect(status().isConflict());
        }
        assertThat(transactions.countByUser(account)).isEqualTo(1);
        assertThat(wallet.getBalance(account)).isEqualByComparingTo("5.00");
        assertThat(wallet.getBalance(other)).isEqualByComparingTo("0.00");
    }

    @ParameterizedTest
    @ValueSource(booleans = {false, true})
    void simultaneousCreditsCommitOnceAndRejectChangedAmounts(boolean changedAmount) throws Exception {
        User account = creditAccount(changedAmount ? 820003L : 820002L);
        String key = "synthetic-credit-" + account.getId();
        synchronizeIdempotencyReads(key, 1);
        ExecutorService pool = Executors.newFixedThreadPool(2);
        try {
            List<Future<Transaction>> attempts = List.of(
                    pool.submit(() -> credit(account, "5.00", key)),
                    pool.submit(() -> credit(account, changedAmount ? "7.00" : "5.00", key)));
            List<Transaction> receipts = new ArrayList<>();
            List<Throwable> failures = new ArrayList<>();
            for (Future<Transaction> attempt : attempts) {
                try {
                    receipts.add(attempt.get(20, TimeUnit.SECONDS));
                } catch (ExecutionException error) {
                    failures.add(error.getCause());
                }
            }
            assertThat(receipts).hasSize(changedAmount ? 1 : 2);
            assertThat(failures).hasSize(changedAmount ? 1 : 0);
            if (changedAmount) {
                assertThat(failures.get(0)).isInstanceOf(IllegalStateException.class);
            } else {
                assertThat(receipts.get(0).getId()).isEqualTo(receipts.get(1).getId());
            }
            assertThat(transactions.countByUser(account)).isEqualTo(1);
            assertThat(wallet.getBalance(account)).isEqualByComparingTo(receipts.get(0).getAmount());
        } finally {
            pool.shutdownNow();
        }
    }

    @Test
    void aGlobalKeyRaceAcrossAccountsRollsBackTheLosingWallet() throws Exception {
        User first = creditAccount(820004L);
        User second = creditAccount(820005L);
        String key = "synthetic-credit-global-collision";
        synchronizeIdempotencyReads(key, 2);
        ExecutorService pool = Executors.newFixedThreadPool(2);
        try {
            List<Future<Transaction>> attempts = List.of(
                    pool.submit(() -> credit(first, "5.00", key)),
                    pool.submit(() -> credit(second, "5.00", key)));
            List<Transaction> receipts = new ArrayList<>();
            List<Throwable> failures = new ArrayList<>();
            for (Future<Transaction> attempt : attempts) {
                try {
                    receipts.add(attempt.get(20, TimeUnit.SECONDS));
                } catch (ExecutionException error) {
                    failures.add(error.getCause());
                }
            }
            assertThat(receipts).hasSize(1);
            assertThat(failures).hasSize(1);
            assertThat(failures.get(0)).isInstanceOf(DataIntegrityViolationException.class);
            User winner = receipts.get(0).getUser().getId().equals(first.getId()) ? first : second;
            User loser = winner == first ? second : first;
            assertThat(wallet.getBalance(winner)).isEqualByComparingTo("5.00");
            assertThat(wallet.getBalance(loser)).isEqualByComparingTo("0.00");
            assertThat(transactions.countByUser(winner)).isEqualTo(1);
            assertThat(transactions.countByUser(loser)).isZero();
            assertThatThrownBy(() -> credit(loser, "5.00", key))
                    .isInstanceOf(IllegalStateException.class);
        } finally {
            pool.shutdownNow();
        }
    }

    private User creditAccount(long id) {
        User account = new User();
        account.setId(id);
        account.setUsername("synthetic-credit-" + id);
        account.setPasswordHash("unused");
        account = users.saveAndFlush(account);
        wallet.getOrCreateWallet(account);
        return account;
    }

    private Transaction credit(User account, String amount, String key) {
        return wallet.credit(account, new BigDecimal(amount), "admin_credit", "synthetic",
                null, null, null, key);
    }

    private void synchronizeIdempotencyReads(String key, int rounds) {
        CyclicBarrier bothRead = new CyclicBarrier(2);
        AtomicInteger reads = new AtomicInteger();
        doAnswer(invocation -> {
            Optional<Transaction> result = entityManager.createQuery(
                            "select t from Transaction t where t.idempotencyKey = :key", Transaction.class)
                    .setParameter("key", key).getResultStream().findFirst();
            if (reads.getAndIncrement() < rounds * 2) bothRead.await(10, TimeUnit.SECONDS);
            return result;
        }).when(transactions).findByIdempotencyKey(eq(key));
    }
}
