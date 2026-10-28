package com.modstore;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.modstore.model.User;
import com.modstore.model.WalletHold;
import com.modstore.repository.UserRepository;
import com.modstore.service.AccountLevelService;
import com.modstore.service.WalletService;
import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.security.Keys;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;
import org.testcontainers.containers.PostgreSQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;

import java.math.BigDecimal;
import java.security.KeyPair;
import java.security.KeyPairGenerator;
import java.security.MessageDigest;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.util.*;
import java.util.concurrent.atomic.AtomicLong;
import java.util.concurrent.*;
import javax.sql.DataSource;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@Testcontainers(disabledWithoutDocker = true)
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT, properties = {"spring.jpa.hibernate.ddl-auto=create-drop", "spring.flyway.enabled=false",
        "llm.wallet.service-enabled=true", "llm.wallet.key-id=synthetic", "llm.wallet.max-cents=10000"})
@AutoConfigureMockMvc
class LlmWalletServiceIntegrationTest {
    @Container static PostgreSQLContainer<?> postgres = new PostgreSQLContainer<>(
            System.getProperty("payment.test.postgres.image", "postgres:16-alpine"));
    static final KeyPair keys = generate();
    static final AtomicLong ids = new AtomicLong(830000L);
    static final String syntheticSecret = UUID.randomUUID().toString() + UUID.randomUUID();
    static KeyPair generate() {
        try { KeyPairGenerator g = KeyPairGenerator.getInstance("RSA"); g.initialize(2048); return g.generateKeyPair(); }
        catch (Exception e) { throw new IllegalStateException(e); }
    }
    @DynamicPropertySource static void properties(DynamicPropertyRegistry registry) {
        registry.add("spring.datasource.url", postgres::getJdbcUrl);
        registry.add("spring.datasource.username", postgres::getUsername);
        registry.add("spring.datasource.password", postgres::getPassword);
        registry.add("jwt.secret", () -> syntheticSecret);
        registry.add("payment.secret-key", () -> syntheticSecret);
        registry.add("spring.security.user.password", () -> syntheticSecret);
        registry.add("llm.wallet.public-key-pem", () -> "-----BEGIN PUBLIC KEY-----\n"
                + Base64.getMimeEncoder(64, new byte[]{'\n'}).encodeToString(keys.getPublic().getEncoded())
                + "\n-----END PUBLIC KEY-----");
    }

    @Autowired MockMvc http;
    @LocalServerPort int port;
    @Autowired UserRepository users;
    @Autowired WalletService wallet;
    @Autowired JdbcTemplate jdbc;
    @Autowired DataSource dataSource;
    @MockitoBean AccountLevelService accountLevel;
    final ObjectMapper json = new ObjectMapper();
    User user;

    @BeforeEach void setUp() {
        jdbc.execute("CREATE TABLE IF NOT EXISTS llm_wallet_service_requests "
                + "(operation_key VARCHAR(192) PRIMARY KEY, user_id BIGINT NOT NULL, operation VARCHAR(16) NOT NULL, request_digest VARCHAR(64) NOT NULL, hold_no VARCHAR(64) NULL)");
        jdbc.execute("CREATE TABLE IF NOT EXISTS llm_wallet_service_nonces "
                + "(nonce VARCHAR(32) PRIMARY KEY, operation_key VARCHAR(192) NOT NULL REFERENCES llm_wallet_service_requests(operation_key))");
        long id = ids.incrementAndGet();
        user = new User(); user.setId(id); user.setUsername("synthetic-wallet-" + id); user.setPasswordHash("unused");
        user = users.saveAndFlush(user);
        wallet.addBalance(user, new BigDecimal("100.00"), "synthetic", "test");
    }

    String sign(byte[] body, String op, long sub, String audience, Instant expiry, String hold) throws Exception {
        String digest = HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(body));
        var builder = Jwts.builder().header().keyId("synthetic").and().issuer("modstore-llm-auth")
                .audience().add(audience).and().subject(Long.toString(sub))
                .issuedAt(Date.from(Instant.now())).expiration(Date.from(expiry))
                .id(UUID.randomUUID().toString().replace("-", ""))
                .claim("operation", op).claim("request_digest", digest).claim("max_amount_cents", 10000);
        if (hold != null) builder.claim("reservation_id", hold);
        return builder.signWith(keys.getPrivate(), Jwts.SIG.RS256).compact();
    }

    String loginToken() {
        return Jwts.builder().subject(user.getId().toString()).claim("type", "access")
                .claim("username", user.getUsername()).expiration(Date.from(Instant.now().plusSeconds(60)))
                .signWith(Keys.hmacShaKeyFor(syntheticSecret.getBytes(java.nio.charset.StandardCharsets.UTF_8)), Jwts.SIG.HS256)
                .compact();
    }

    @Test void accountBoundLifecycleAndReplay() throws Exception {
        byte[] pre = json.writeValueAsBytes(Map.of("amount", "5.00", "provider", "synthetic", "model", "model",
                "request_id", "synthetic-request", "idempotency_key", "synthetic-request:preauth"));
        String token = sign(pre, "preauthorize", user.getId(), "modstore-llm-wallet", Instant.now().plusSeconds(40), null);
        var response = http.perform(post("/api/internal/llm-wallet/preauthorize").header("X-Llm-Wallet-Assertion", token)
                .contentType("application/json").content(pre)).andExpect(status().isOk()).andReturn();
        String hold = json.readTree(response.getResponse().getContentAsByteArray()).path("hold").path("hold_no").asText();
        http.perform(post("/api/internal/llm-wallet/preauthorize").header("X-Llm-Wallet-Assertion", token)
                .contentType("application/json").content(pre)).andExpect(status().isOk());
        assertThat(wallet.getBalance(user)).isEqualByComparingTo("95.00");
        byte[] ordinarySettle = json.writeValueAsBytes(Map.of("hold_no", hold, "actual_amount", "0.00", "idempotency_key", "ordinary-zero"));
        var rejectedSettle = http.perform(post("/api/wallet/ai/settle").header("Authorization", "Bearer " + loginToken())
                .contentType("application/json").content(ordinarySettle)).andExpect(status().isOk()).andReturn();
        assertThat(json.readTree(rejectedSettle.getResponse().getContentAsByteArray()).path("ok").asBoolean()).isFalse();
        byte[] ordinaryRelease = json.writeValueAsBytes(Map.of("hold_no", hold, "reason", "synthetic", "idempotency_key", "ordinary-release"));
        var rejectedRelease = http.perform(post("/api/wallet/ai/release").header("Authorization", "Bearer " + loginToken())
                .contentType("application/json").content(ordinaryRelease)).andExpect(status().isOk()).andReturn();
        assertThat(json.readTree(rejectedRelease.getResponse().getContentAsByteArray()).path("ok").asBoolean()).isFalse();
        assertThat(wallet.getBalance(user)).isEqualByComparingTo("95.00");
        byte[] changed = json.writeValueAsBytes(Map.of("amount", "6.00", "provider", "synthetic", "model", "model",
                "request_id", "synthetic-request", "idempotency_key", "synthetic-request:preauth"));
        http.perform(post("/api/internal/llm-wallet/preauthorize")
                .header("X-Llm-Wallet-Assertion", sign(changed, "preauthorize", user.getId(), "modstore-llm-wallet", Instant.now().plusSeconds(40), null))
                .contentType("application/json").content(changed)).andExpect(status().isUnauthorized());
        user.setAccountState("disabled");
        user = users.saveAndFlush(user);
        http.perform(post("/api/internal/llm-wallet/preauthorize")
                .header("X-Llm-Wallet-Assertion", token)
                .contentType("application/json").content(pre)).andExpect(status().isOk());
        byte[] settle = json.writeValueAsBytes(Map.of("hold_no", hold, "actual_amount", "2.00",
                "request_id", "synthetic-request", "idempotency_key", "synthetic-request:settle"));
        User other = new User();
        other.setId(ids.incrementAndGet());
        other.setUsername("synthetic-wallet-" + other.getId());
        other.setPasswordHash("unused");
        users.saveAndFlush(other);
        http.perform(post("/api/internal/llm-wallet/settle")
                .header("X-Llm-Wallet-Assertion", sign(settle, "settle", other.getId(), "modstore-llm-wallet", Instant.now().plusSeconds(40), hold))
                .contentType("application/json").content(settle)).andExpect(status().isUnauthorized());
        String settleToken = sign(settle, "settle", user.getId(), "modstore-llm-wallet", Instant.now().plusSeconds(40), hold);
        http.perform(post("/api/internal/llm-wallet/settle")
                .header("X-Llm-Wallet-Assertion", settleToken)
                .contentType("application/json").content(settle)).andExpect(status().isOk());
        http.perform(post("/api/internal/llm-wallet/settle")
                .header("X-Llm-Wallet-Assertion", settleToken)
                .contentType("application/json").content(settle)).andExpect(status().isOk());
        assertThat(wallet.getBalance(user)).isEqualByComparingTo("98.00");
        http.perform(post("/api/internal/llm-wallet/preauthorize")
                .header("X-Llm-Wallet-Assertion", token).contentType("application/json").content(pre))
                .andExpect(status().isConflict());
    }

    @Test void unavailableReplayDatabaseFailsClosed() throws Exception {
        jdbc.execute("DROP TABLE llm_wallet_service_nonces");
        jdbc.execute("DROP TABLE llm_wallet_service_requests");
        byte[] body = json.writeValueAsBytes(Map.of("amount", "5.00", "provider", "synthetic", "model", "model",
                "request_id", "db-failure", "idempotency_key", "db-failure:preauth"));
        http.perform(post("/api/internal/llm-wallet/preauthorize")
                .header("X-Llm-Wallet-Assertion", sign(body, "preauthorize", user.getId(), "modstore-llm-wallet", Instant.now().plusSeconds(40), null))
                .contentType("application/json").content(body)).andExpect(status().isServiceUnavailable());
        assertThat(wallet.getBalance(user)).isEqualByComparingTo("100.00");
    }

    @Test void failureAfterDebitRollsBackHoldAndReplayThenRetrySucceeds() throws Exception {
        jdbc.execute("CREATE OR REPLACE FUNCTION synthetic_hold_failure() RETURNS trigger LANGUAGE plpgsql "
                + "AS $$ BEGIN RAISE EXCEPTION 'synthetic failure'; END $$");
        jdbc.execute("CREATE TRIGGER synthetic_hold_failure BEFORE UPDATE OF hold_no ON llm_wallet_service_requests "
                + "FOR EACH ROW EXECUTE PROCEDURE synthetic_hold_failure()");
        byte[] body = json.writeValueAsBytes(Map.of("amount", "5.00", "provider", "synthetic", "model", "model",
                "request_id", "rollback-retry", "idempotency_key", "rollback-retry:preauth"));
        String token = sign(body, "preauthorize", user.getId(), "modstore-llm-wallet", Instant.now().plusSeconds(40), null);
        try {
            http.perform(post("/api/internal/llm-wallet/preauthorize").header("X-Llm-Wallet-Assertion", token)
                    .contentType("application/json").content(body)).andExpect(status().isServiceUnavailable());
            assertThat(wallet.getBalance(user)).isEqualByComparingTo("100.00");
            assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM wallet_holds WHERE request_id='rollback-retry'", Long.class)).isZero();
            assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM transactions WHERE reference_no='rollback-retry'", Long.class)).isZero();
            assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM llm_wallet_service_requests WHERE operation_key='preauthorize:rollback-retry:preauth'", Long.class)).isZero();
            assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM llm_wallet_service_nonces WHERE operation_key='preauthorize:rollback-retry:preauth'", Long.class)).isZero();
        } finally {
            jdbc.execute("DROP TRIGGER synthetic_hold_failure ON llm_wallet_service_requests");
        }
        http.perform(post("/api/internal/llm-wallet/preauthorize").header("X-Llm-Wallet-Assertion", token)
                .contentType("application/json").content(body)).andExpect(status().isOk());
        assertThat(wallet.getBalance(user)).isEqualByComparingTo("95.00");
    }

    @Test void insufficientBalanceDoesNotCreateReservationOrReplayRecord() throws Exception {
        wallet.deductBalance(user, new BigDecimal("99.00"), "synthetic", "test");
        byte[] body = json.writeValueAsBytes(Map.of("amount", "5.00", "provider", "synthetic", "model", "model",
                "request_id", "insufficient", "idempotency_key", "insufficient:preauth"));
        http.perform(post("/api/internal/llm-wallet/preauthorize")
                .header("X-Llm-Wallet-Assertion", sign(body, "preauthorize", user.getId(), "modstore-llm-wallet", Instant.now().plusSeconds(40), null))
                .contentType("application/json").content(body)).andExpect(status().isPaymentRequired());
        assertThat(wallet.getBalance(user)).isEqualByComparingTo("1.00");
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM llm_wallet_service_requests WHERE operation_key=?", Long.class,
                "preauthorize:insufficient:preauth")).isZero();
    }

    @Test void settlementAboveHoldIsChargedButAboveServiceLimitLeavesHold() throws Exception {
        byte[] pre = json.writeValueAsBytes(Map.of("amount", "5.00", "provider", "synthetic", "model", "model",
                "request_id", "extra-charge", "idempotency_key", "extra-charge:preauth"));
        var response = http.perform(post("/api/internal/llm-wallet/preauthorize")
                .header("X-Llm-Wallet-Assertion", sign(pre, "preauthorize", user.getId(), "modstore-llm-wallet", Instant.now().plusSeconds(40), null))
                .contentType("application/json").content(pre)).andExpect(status().isOk()).andReturn();
        String hold = json.readTree(response.getResponse().getContentAsByteArray()).path("hold").path("hold_no").asText();
        byte[] overLimit = json.writeValueAsBytes(Map.of("hold_no", hold, "actual_amount", "100.01",
                "request_id", "extra-charge", "idempotency_key", "extra-charge:settle"));
        http.perform(post("/api/internal/llm-wallet/settle")
                .header("X-Llm-Wallet-Assertion", sign(overLimit, "settle", user.getId(), "modstore-llm-wallet", Instant.now().plusSeconds(40), hold))
                .contentType("application/json").content(overLimit)).andExpect(status().isUnauthorized());
        assertThat(wallet.getBalance(user)).isEqualByComparingTo("95.00");
        byte[] extra = json.writeValueAsBytes(Map.of("hold_no", hold, "actual_amount", "7.00",
                "request_id", "extra-charge", "idempotency_key", "extra-charge:settle"));
        http.perform(post("/api/internal/llm-wallet/settle")
                .header("X-Llm-Wallet-Assertion", sign(extra, "settle", user.getId(), "modstore-llm-wallet", Instant.now().plusSeconds(40), hold))
                .contentType("application/json").content(extra)).andExpect(status().isOk());
        assertThat(wallet.getBalance(user)).isEqualByComparingTo("93.00");
    }

    @Test void ordinaryWalletHoldCannotBeSettledOrReleasedThroughService() throws Exception {
        WalletHold legacy = wallet.preauthorizeAiUsage(user, new BigDecimal("5.00"), "synthetic", "model",
                "legacy-request", "legacy-request:preauth");
        byte[] adopt = json.writeValueAsBytes(Map.of("amount", "5.00", "provider", "synthetic", "model", "model",
                "request_id", "legacy-request", "idempotency_key", "legacy-request:preauth"));
        http.perform(post("/api/internal/llm-wallet/preauthorize")
                .header("X-Llm-Wallet-Assertion", sign(adopt, "preauthorize", user.getId(), "modstore-llm-wallet", Instant.now().plusSeconds(40), null))
                .contentType("application/json").content(adopt)).andExpect(status().isUnauthorized());
        byte[] settle = json.writeValueAsBytes(Map.of("hold_no", legacy.getHoldNo(), "actual_amount", "2.00",
                "request_id", "legacy-request", "idempotency_key", "legacy-request:settle"));
        http.perform(post("/api/internal/llm-wallet/settle")
                .header("X-Llm-Wallet-Assertion", sign(settle, "settle", user.getId(), "modstore-llm-wallet", Instant.now().plusSeconds(40), legacy.getHoldNo()))
                .contentType("application/json").content(settle)).andExpect(status().isUnauthorized());
        byte[] release = json.writeValueAsBytes(Map.of("hold_no", legacy.getHoldNo(), "reason", "synthetic",
                "request_id", "legacy-request", "idempotency_key", "legacy-request:release"));
        http.perform(post("/api/internal/llm-wallet/release")
                .header("X-Llm-Wallet-Assertion", sign(release, "release", user.getId(), "modstore-llm-wallet", Instant.now().plusSeconds(40), legacy.getHoldNo()))
                .contentType("application/json").content(release)).andExpect(status().isUnauthorized());
        assertThat(wallet.getBalance(user)).isEqualByComparingTo("95.00");
    }

    @Test void repeatedPreauthorizationWaitsForHoldAndRejectsTerminalState() throws Exception {
        byte[] body = json.writeValueAsBytes(Map.of("amount", "5.00", "provider", "synthetic", "model", "model",
                "request_id", "hold-race", "idempotency_key", "hold-race:preauth"));
        String token = sign(body, "preauthorize", user.getId(), "modstore-llm-wallet", Instant.now().plusSeconds(40), null);
        var first = http.perform(post("/api/internal/llm-wallet/preauthorize").header("X-Llm-Wallet-Assertion", token)
                .contentType("application/json").content(body)).andExpect(status().isOk()).andReturn();
        String hold = json.readTree(first.getResponse().getContentAsByteArray()).path("hold").path("hold_no").asText();
        ExecutorService pool = Executors.newSingleThreadExecutor();
        try (var connection = dataSource.getConnection()) {
            connection.setAutoCommit(false);
            try (var lock = connection.prepareStatement("SELECT id FROM wallet_holds WHERE hold_no=? FOR UPDATE")) {
                lock.setString(1, hold);
                lock.executeQuery().close();
            }
            Future<Integer> response = pool.submit(() -> http.perform(post("/api/internal/llm-wallet/preauthorize")
                    .header("X-Llm-Wallet-Assertion", token).contentType("application/json").content(body))
                    .andReturn().getResponse().getStatus());
            assertThatThrownBy(() -> response.get(500, TimeUnit.MILLISECONDS)).isInstanceOf(TimeoutException.class);
            try (var finish = connection.prepareStatement("UPDATE wallet_holds SET status='settled' WHERE hold_no=?")) {
                finish.setString(1, hold);
                finish.executeUpdate();
            }
            connection.commit();
            assertThat(response.get(10, TimeUnit.SECONDS)).isEqualTo(409);
            assertThat(wallet.getBalance(user)).isEqualByComparingTo("95.00");
        } finally {
            pool.shutdownNow();
        }
    }

    @Test
    @EnabledIfSystemProperty(named = "llm.python", matches = ".+")
    void pythonGatewayToJavaWalletUsesSameAccountAndFinishesAfterRevocation(@TempDir Path temp) throws Exception {
        Path privateKey = temp.resolve("synthetic-key.pem");
        Files.writeString(privateKey, "-----BEGIN " + "PRIVATE KEY-----\n"
                + Base64.getMimeEncoder(64, new byte[]{'\n'}).encodeToString(keys.getPrivate().getEncoded())
                + "\n-----END " + "PRIVATE KEY-----");
        privateKey.toFile().setReadable(false, false);
        privateKey.toFile().setReadable(true, true);
        ProcessBuilder process = new ProcessBuilder(System.getProperty("llm.python"),
                "src/test/resources/llm_pat_bridge.py", user.getId().toString(),
                "http://127.0.0.1:" + port, privateKey.toString(), temp.resolve("synthetic.sqlite").toString());
        process.environment().put("PYTHONPATH", Path.of("..").toAbsolutePath().normalize().toString());
        process.redirectErrorStream(true);
        Process child = process.start();
        String output = new String(child.getInputStream().readAllBytes(), java.nio.charset.StandardCharsets.UTF_8);
        assertThat(child.waitFor()).as("synthetic Python bridge: %s", output).isZero();
        assertThat(output).contains("synthetic bridge passed");
        assertThat(wallet.getBalance(user)).isEqualByComparingTo("99.98");
    }

    @Test void rejectsWrongAudienceOperationAndExpiry() throws Exception {
        byte[] body = json.writeValueAsBytes(Map.of("amount", "5.00", "provider", "synthetic", "model", "model",
                "request_id", "other-request", "idempotency_key", "other-request:preauth"));
        for (String token : List.of(
                sign(body, "preauthorize", user.getId(), "wrong", Instant.now().plusSeconds(40), null),
                sign(body, "release", user.getId(), "modstore-llm-wallet", Instant.now().plusSeconds(40), "hold"),
                sign(body, "preauthorize", user.getId(), "modstore-llm-wallet", Instant.now().minusSeconds(1), null))) {
            http.perform(post("/api/internal/llm-wallet/preauthorize").header("X-Llm-Wallet-Assertion", token)
                    .contentType("application/json").content(body)).andExpect(status().isUnauthorized());
        }
        String signed = sign(body, "preauthorize", user.getId(), "modstore-llm-wallet", Instant.now().plusSeconds(40), null);
        String[] pieces = signed.split("\\.");
        pieces[2] = (pieces[2].charAt(0) == 'A' ? "B" : "A") + pieces[2].substring(1);
        http.perform(post("/api/internal/llm-wallet/preauthorize")
                .header("X-Llm-Wallet-Assertion", String.join(".", pieces))
                .contentType("application/json").content(body)).andExpect(status().isUnauthorized());
        byte[] tooLarge = json.writeValueAsBytes(Map.of("amount", "100.01", "provider", "synthetic", "model", "model",
                "request_id", "too-large", "idempotency_key", "too-large:preauth"));
        http.perform(post("/api/internal/llm-wallet/preauthorize")
                .header("X-Llm-Wallet-Assertion", sign(tooLarge, "preauthorize", user.getId(), "modstore-llm-wallet", Instant.now().plusSeconds(40), null))
                .contentType("application/json").content(tooLarge)).andExpect(status().isUnauthorized());
        assertThat(wallet.getBalance(user)).isEqualByComparingTo("100.00");
    }

    @Test void cannotUsePatOnOrdinaryWalletOrOverrideAccountInBody() throws Exception {
        String syntheticPat = "pat_" + UUID.randomUUID().toString().replace("-", "");
        http.perform(post("/api/wallet/ai/preauthorize").header("Authorization", "Bearer " + syntheticPat)
                .contentType("application/json").content("{}"))
                .andExpect(status().isUnauthorized());
        byte[] body = json.writeValueAsBytes(Map.of("amount", "5.00", "provider", "synthetic", "model", "model",
                "request_id", "body-override", "idempotency_key", "body-override:preauth", "user_id", 99999));
        http.perform(post("/api/internal/llm-wallet/preauthorize")
                .header("X-Llm-Wallet-Assertion", sign(body, "preauthorize", user.getId(), "modstore-llm-wallet", Instant.now().plusSeconds(40), null))
                .contentType("application/json").content(body)).andExpect(status().isUnauthorized());
        assertThat(wallet.getBalance(user)).isEqualByComparingTo("100.00");
    }
}
