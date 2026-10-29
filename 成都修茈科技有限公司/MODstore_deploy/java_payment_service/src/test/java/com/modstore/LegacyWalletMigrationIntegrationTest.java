package com.modstore;

import com.modstore.repository.UserRepository;
import com.modstore.repository.WalletHoldRepository;
import com.modstore.service.AccountLevelService;
import com.modstore.service.WalletService;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.security.Keys;
import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;
import org.testcontainers.containers.PostgreSQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;

import java.sql.DriverManager;
import java.util.UUID;
import java.util.Date;
import java.time.Instant;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@Testcontainers(disabledWithoutDocker = true)
@SpringBootTest(properties = {"spring.jpa.hibernate.ddl-auto=validate", "spring.flyway.enabled=true"})
@AutoConfigureMockMvc
class LegacyWalletMigrationIntegrationTest {
    @Container static PostgreSQLContainer<?> postgres = new PostgreSQLContainer<>(
            System.getProperty("payment.test.postgres.image", "postgres:16-alpine"));
    static final String syntheticSecret = UUID.randomUUID().toString() + UUID.randomUUID();
    @DynamicPropertySource static void properties(DynamicPropertyRegistry registry) {
        Flyway.configure().dataSource(postgres.getJdbcUrl(), postgres.getUsername(), postgres.getPassword())
                .target("17").load().migrate();
        try (var connection = DriverManager.getConnection(postgres.getJdbcUrl(), postgres.getUsername(), postgres.getPassword());
             var statement = connection.createStatement()) {
            statement.execute("INSERT INTO users(id,username,password_hash) VALUES (840001,'synthetic-legacy','unused')");
            statement.execute("INSERT INTO wallets(user_id,balance) VALUES (840001,90.00)");
            statement.execute("INSERT INTO wallet_holds(user_id,hold_no,amount,status,idempotency_key,request_id) VALUES "
                    + "(840001,'legacy-settle',5.00,'held','legacy-settle-key','legacy-settle-request'),"
                    + "(840001,'legacy-release',5.00,'held','legacy-release-key','legacy-release-request')");
        } catch (Exception error) { throw new IllegalStateException(error); }
        registry.add("spring.datasource.url", postgres::getJdbcUrl);
        registry.add("spring.datasource.username", postgres::getUsername);
        registry.add("spring.datasource.password", postgres::getPassword);
        registry.add("jwt.secret", () -> syntheticSecret);
        registry.add("payment.secret-key", () -> syntheticSecret);
        registry.add("spring.security.user.password", () -> syntheticSecret);
    }
    @Autowired UserRepository users;
    @Autowired WalletHoldRepository holds;
    @Autowired WalletService wallet;
    @Autowired MockMvc http;
    @MockitoBean AccountLevelService accountLevel;

    @Test void existingV17HoldsRemainUsableAfterV18() throws Exception {
        var user = users.findById(840001L).orElseThrow();
        assertThat(holds.findByHoldNo("legacy-settle").orElseThrow().getBillingSource()).isEqualTo("legacy");
        assertThat(holds.findByHoldNo("legacy-release").orElseThrow().getBillingSource()).isEqualTo("legacy");
        String jwt = Jwts.builder().subject(user.getId().toString()).claim("type", "access")
                .claim("username", user.getUsername()).expiration(Date.from(Instant.now().plusSeconds(60)))
                .signWith(Keys.hmacShaKeyFor(syntheticSecret.getBytes(java.nio.charset.StandardCharsets.UTF_8)), Jwts.SIG.HS256).compact();
        ObjectMapper json = new ObjectMapper();
        var settled = http.perform(post("/api/wallet/ai/settle").header("Authorization", "Bearer " + jwt)
                .contentType("application/json").content(json.writeValueAsBytes(Map.of("hold_no", "legacy-settle", "actual_amount", "2.00", "idempotency_key", "legacy-settle-op"))))
                .andExpect(status().isOk()).andReturn();
        assertThat(json.readTree(settled.getResponse().getContentAsByteArray()).path("ok").asBoolean()).isTrue();
        var released = http.perform(post("/api/wallet/ai/release").header("Authorization", "Bearer " + jwt)
                .contentType("application/json").content(json.writeValueAsBytes(Map.of("hold_no", "legacy-release", "reason", "synthetic", "idempotency_key", "legacy-release-op"))))
                .andExpect(status().isOk()).andReturn();
        assertThat(json.readTree(released.getResponse().getContentAsByteArray()).path("ok").asBoolean()).isTrue();
        assertThat(wallet.getBalance(user)).isEqualByComparingTo("98.00");
    }
}
