package com.modstore.controller;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.modstore.model.User;
import com.modstore.model.WalletHold;
import com.modstore.repository.UserRepository;
import com.modstore.repository.WalletHoldRepository;
import com.modstore.repository.WalletRepository;
import com.modstore.service.WalletService;
import io.jsonwebtoken.Claims;
import io.jsonwebtoken.Jwts;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.dao.DataAccessException;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;

import java.math.BigDecimal;
import java.security.KeyFactory;
import java.security.MessageDigest;
import java.security.interfaces.RSAPublicKey;
import java.security.spec.X509EncodedKeySpec;
import java.time.Instant;
import java.util.Base64;
import java.util.HexFormat;
import java.util.Map;
import java.util.Set;

/** Disabled unless explicitly configured; never accepts a user login token. */
@RestController
@RequestMapping("/api/internal/llm-wallet")
@ConditionalOnProperty(name = "llm.wallet.service-enabled", havingValue = "true")
public class LlmWalletServiceController {
    private final WalletService wallet;
    private final WalletHoldRepository holds;
    private final WalletRepository wallets;
    private final UserRepository users;
    private final JdbcTemplate jdbc;
    private final ObjectMapper json = new ObjectMapper();
    private final String publicKeyPem;
    private final String keyId;
    private final long maxCents;

    public LlmWalletServiceController(WalletService wallet, WalletHoldRepository holds, WalletRepository wallets,
            UserRepository users, JdbcTemplate jdbc,
            @Value("${llm.wallet.public-key-pem:}") String publicKeyPem,
            @Value("${llm.wallet.key-id:}") String keyId,
            @Value("${llm.wallet.max-cents:0}") long maxCents) {
        this.wallet = wallet;
        this.holds = holds;
        this.wallets = wallets;
        this.users = users;
        this.jdbc = jdbc;
        this.publicKeyPem = publicKeyPem;
        this.keyId = keyId;
        this.maxCents = maxCents;
    }

    @PostMapping("/{operation}")
    @Transactional
    public Map<String, Object> execute(@PathVariable String operation,
            @RequestHeader(value = "X-Llm-Wallet-Assertion", required = false) String assertion,
            @RequestBody byte[] rawBody) {
        if (!Set.of("preauthorize", "settle", "release").contains(operation)) throw denied();
        if (keyId.isBlank() || publicKeyPem.isBlank() || maxCents <= 0) {
            throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "模型计费服务未配置");
        }
        if (assertion == null || assertion.length() > 4096 || rawBody.length > 4096) throw denied();
        RSAPublicKey key;
        try {
            String keyData = publicKeyPem.replace("-----BEGIN PUBLIC KEY-----", "")
                    .replace("-----END PUBLIC KEY-----", "").replaceAll("\\s", "");
            key = (RSAPublicKey) KeyFactory.getInstance("RSA")
                    .generatePublic(new X509EncodedKeySpec(Base64.getDecoder().decode(keyData)));
            if (key.getModulus().bitLength() < 2048) throw new IllegalArgumentException();
        } catch (java.security.GeneralSecurityException | IllegalArgumentException | ClassCastException e) {
            throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "模型计费服务未配置");
        }
        try {
            var signed = Jwts.parser().verifyWith(key).requireIssuer("modstore-llm-auth")
                    .requireAudience("modstore-llm-wallet").build().parseSignedClaims(assertion);
            Claims c = signed.getPayload();
            long now = Instant.now().getEpochSecond();
            if (!"RS256".equals(signed.getHeader().getAlgorithm())
                    || !keyId.equals(signed.getHeader().getKeyId())
                    || c.getIssuedAt() == null || c.getExpiration() == null
                    || c.getIssuedAt().toInstant().getEpochSecond() > now
                    || c.getExpiration().toInstant().getEpochSecond() - c.getIssuedAt().toInstant().getEpochSecond() > 60
                    || !operation.equals(c.get("operation", String.class))) throw denied();
            String digest = HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(rawBody));
            if (!digest.equals(c.get("request_digest", String.class))) throw denied();
            String nonce = c.getId();
            if (nonce == null || !nonce.matches("[0-9a-f]{32}")) throw denied();
            long userId = Long.parseLong(c.getSubject());
            if (userId <= 0) throw denied();
            long claimLimit = ((Number) c.get("max_amount_cents")).longValue();
            if (claimLimit <= 0 || claimLimit > maxCents) throw denied();
            Map<String, Object> body = json.readValue(rawBody, new TypeReference<>() {});
            Set<String> fields = operation.equals("preauthorize")
                    ? Set.of("amount", "provider", "model", "request_id", "idempotency_key")
                    : operation.equals("settle")
                        ? Set.of("hold_no", "actual_amount", "request_id", "idempotency_key")
                        : Set.of("hold_no", "reason", "request_id", "idempotency_key");
            if (!body.keySet().equals(fields)) throw denied();
            String requestId = text(body, "request_id", 128);
            String idem = text(body, "idempotency_key", 128);
            if (!idem.equals(requestId + ":" + (operation.equals("preauthorize") ? "preauth" : operation))) throw denied();
            String opKey = operation + ":" + idem;
            User user = users.findById(userId).orElseThrow(LlmWalletServiceController::denied);
            jdbc.update("INSERT INTO llm_wallet_service_requests(operation_key,user_id,operation,request_digest) "
                    + "VALUES (?,?,?,?) ON CONFLICT (operation_key) DO NOTHING", opKey, userId, operation, digest);
            var record = jdbc.queryForMap("SELECT user_id,operation,request_digest,hold_no FROM llm_wallet_service_requests "
                    + "WHERE operation_key=? FOR UPDATE", opKey);
            if (((Number) record.get("user_id")).longValue() != userId
                    || !operation.equals(record.get("operation")) || !digest.equals(record.get("request_digest"))) throw denied();
            jdbc.update("INSERT INTO llm_wallet_service_nonces(nonce,operation_key) VALUES (?,?) "
                    + "ON CONFLICT (nonce) DO NOTHING", nonce, opKey);
            String nonceOwner = jdbc.queryForObject("SELECT operation_key FROM llm_wallet_service_nonces WHERE nonce=?", String.class, nonce);
            if (!opKey.equals(nonceOwner)) throw denied();
            WalletHold hold;
            if (operation.equals("preauthorize")) {
                if (c.get("reservation_id") != null) throw denied();
                BigDecimal amount = amount(body, "amount", claimLimit, false);
                Object boundHold = record.get("hold_no");
                if (boundHold == null) {
                    wallet.getOrCreateWallet(user);
                    wallets.findByUserIdForUpdate(userId).orElseThrow(LlmWalletServiceController::denied);
                    if (holds.findByIdempotencyKey(idem).isPresent()) throw denied();
                } else {
                    WalletHold prior = holds.findByHoldNoForUpdate(String.valueOf(boundHold))
                            .orElseThrow(LlmWalletServiceController::denied);
                    if (!prior.getUser().getId().equals(userId) || !idem.equals(prior.getIdempotencyKey())
                            || !"llm-service".equals(prior.getBillingSource())) throw denied();
                    if (!"held".equals(prior.getStatus())) {
                        throw new ResponseStatusException(HttpStatus.CONFLICT, "预授权已终结");
                    }
                }
                hold = wallet.preauthorizeAiUsage(user, amount, text(body, "provider", 64),
                        text(body, "model", 128), requestId, idem);
                if (boundHold != null && !boundHold.equals(hold.getHoldNo())) throw denied();
                if (!"held".equals(hold.getStatus())) {
                    throw new ResponseStatusException(HttpStatus.CONFLICT, "预授权已终结");
                }
                hold.setBillingSource("llm-service");
                holds.saveAndFlush(hold);
                jdbc.update("UPDATE llm_wallet_service_requests SET hold_no=? WHERE operation_key=?", hold.getHoldNo(), opKey);
            } else {
                String holdNo = text(body, "hold_no", 64);
                if (!holdNo.equals(c.get("reservation_id", String.class))) throw denied();
                var origins = jdbc.queryForList("SELECT user_id,hold_no FROM llm_wallet_service_requests "
                        + "WHERE operation_key=? AND operation='preauthorize' FOR UPDATE", "preauthorize:" + requestId + ":preauth");
                if (origins.size() != 1 || ((Number) origins.get(0).get("user_id")).longValue() != userId
                        || !holdNo.equals(origins.get(0).get("hold_no"))) throw denied();
                WalletHold existing = holds.findByHoldNoForUpdate(holdNo).orElseThrow(LlmWalletServiceController::denied);
                if (!existing.getUser().getId().equals(userId) || !requestId.equals(existing.getRequestId())) throw denied();
                hold = operation.equals("settle")
                        ? wallet.settleServiceAiUsage(user, holdNo, amount(body, "actual_amount", claimLimit, true), idem)
                        : wallet.releaseServiceAiUsage(user, holdNo, text(body, "reason", 256), idem);
                if (operation.equals("release") && !"released".equals(hold.getStatus())) {
                    throw new ResponseStatusException(HttpStatus.CONFLICT, "预授权已终结");
                }
            }
            return Map.of("ok", true, "hold", Map.of("hold_no", hold.getHoldNo(), "amount", hold.getAmount(), "status", hold.getStatus(), "settled_amount", hold.getSettledAmount()));
        } catch (ResponseStatusException e) {
            throw e;
        } catch (DataAccessException e) {
            throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "模型计费暂不可用");
        } catch (IllegalArgumentException e) {
            if ("余额不足".equals(e.getMessage())) {
                throw new ResponseStatusException(HttpStatus.PAYMENT_REQUIRED, "余额不足");
            }
            throw denied();
        } catch (io.jsonwebtoken.JwtException | java.security.GeneralSecurityException
                 | java.io.IOException | ClassCastException | NullPointerException | IllegalStateException e) {
            throw denied();
        } catch (Exception e) {
            throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "模型计费暂不可用");
        }
    }

    private static String text(Map<String, Object> body, String field, int max) {
        Object raw = body.get(field);
        if (!(raw instanceof String value) || value.isBlank() || value.length() > max) throw denied();
        return value;
    }

    private static BigDecimal amount(Map<String, Object> body, String field, long maxCents, boolean zeroAllowed) {
        String value = text(body, field, 20);
        if (!value.matches("[0-9]+\\.[0-9]{2}")) throw denied();
        BigDecimal amount = new BigDecimal(value);
        if ((!zeroAllowed && amount.signum() == 0) || amount.movePointRight(2).compareTo(BigDecimal.valueOf(maxCents)) > 0) throw denied();
        return amount;
    }

    private static ResponseStatusException denied() {
        return new ResponseStatusException(HttpStatus.UNAUTHORIZED, "模型计费请求无效");
    }
}
