package com.modstore.service;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;

import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.nio.charset.StandardCharsets;
import java.util.Locale;
import java.time.Duration;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.UUID;

@Slf4j
@Service
@RequiredArgsConstructor
public class SecurityService {
    
    private final StringRedisTemplate redisTemplate;

    @Value("${payment.secret-key}")
    private String paymentSecretKey;
    
    private static final long REPLAY_WINDOW_SECONDS = 300;
    private static final long NOTIFY_IDEMPOTENCY_SECONDS = 86_400;
    
    public boolean checkReplayAttack(String requestId, long timestamp) {
        // 检查时间戳是否在有效窗口内
        long currentTime = System.currentTimeMillis() / 1000;
        if (Math.abs(currentTime - timestamp) > REPLAY_WINDOW_SECONDS) {
            log.warn("请求时间戳过期: requestId={}, timestamp={}", requestId, timestamp);
            return true;
        }
        
        if (requestId == null || requestId.isBlank()) {
            return true;
        }

        String key = "payment:nonce:" + requestId;
        try {
            Boolean accepted = redisTemplate.opsForValue()
                    .setIfAbsent(key, "1", Duration.ofSeconds(REPLAY_WINDOW_SECONDS));
            if (!Boolean.TRUE.equals(accepted)) {
                log.warn("请求ID已处理: requestId={}", requestId);
                return true;
            }
        } catch (Exception e) {
            // Redis 不可用时放行本次下单，避免整站支付瘫痪；日志便于运维补 Redis
            log.error("支付防重放 Redis 不可用，已降级放行: requestId={}", requestId, e);
        }
        return false;
    }
    
    public boolean verifySignature(Map<String, Object> data, String signature) {
        try {
            Map<String, Object> canonical = canonicalCheckoutData(data);
            String signString = buildSignString(canonical) + paymentSecretKey;
            String calculatedSignature = generateSHA256(signString);
            return constantTimeEqualsHex(calculatedSignature, signature);
        } catch (Exception e) {
            log.error("签名验证失败", e);
            return false;
        }
    }

    public String signCheckout(Map<String, Object> data) {
        try {
            return generateSHA256(buildSignString(canonicalCheckoutData(data)) + paymentSecretKey);
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException("SHA-256 不可用", e);
        }
    }

    public Map<String, Object> canonicalCheckoutData(Map<String, Object> data) {
        if (data == null) {
            throw new IllegalArgumentException("结账数据不能为空");
        }
        Map<String, Object> canonical = new LinkedHashMap<>();
        canonical.put("item_id", String.valueOf(asLong(data.get("item_id"))));
        canonical.put("plan_id", stringValue(data.get("plan_id")));
        canonical.put("request_id", stringValue(data.get("request_id")));
        canonical.put("subject", stringValue(data.get("subject")));
        canonical.put("timestamp", String.valueOf(asLong(data.get("timestamp"))));
        canonical.put("total_amount", amountSignString(data.get("total_amount")));
        canonical.put("wallet_recharge", asBoolean(data.get("wallet_recharge")) ? "true" : "false");
        return canonical;
    }
    
    private String buildSignString(Map<String, Object> data) {
        // 按字典序排序并拼接
        return data.keySet().stream()
                .sorted()
                .map(key -> key + "=" + data.get(key))
                .reduce((a, b) -> a + "&" + b)
                .orElse("");
    }
    
    static boolean constantTimeEqualsHex(String a, String b) {
        if (a == null || b == null) {
            return false;
        }
        String aa = a.toLowerCase(Locale.ROOT);
        String bb = b.toLowerCase(Locale.ROOT);
        if (aa.length() != bb.length()) {
            return false;
        }
        return MessageDigest.isEqual(aa.getBytes(StandardCharsets.US_ASCII), bb.getBytes(StandardCharsets.US_ASCII));
    }

    private String generateSHA256(String input) throws NoSuchAlgorithmException {
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        byte[] hash = digest.digest(input.getBytes(StandardCharsets.UTF_8));
        StringBuilder hexString = new StringBuilder();
        for (byte b : hash) {
            String hex = Integer.toHexString(0xff & b);
            if (hex.length() == 1) {
                hexString.append('0');
            }
            hexString.append(hex);
        }
        return hexString.toString();
    }
    
    public String generateRequestId() {
        return UUID.randomUUID().toString().replace("-", "");
    }

    /**
     * 首次通知返回 true；重复返回 false。Redis 不可用时返回 true 以继续落单（与 {@link #checkReplayAttack} 降级策略一致），
     * 避免误把「无法去重」当成「已处理」而跳过支付宝回调。
     */
    public boolean markAlipayNotifySeen(String tradeNo, String outTradeNo) {
        String identifier = tradeNo == null || tradeNo.isBlank() ? outTradeNo : tradeNo;
        if (identifier == null || identifier.isBlank()) {
            return false;
        }
        String key = "payment:notify:" + identifier;
        try {
            Boolean accepted = redisTemplate.opsForValue()
                    .setIfAbsent(key, "1", Duration.ofSeconds(NOTIFY_IDEMPOTENCY_SECONDS));
            return Boolean.TRUE.equals(accepted);
        } catch (Exception e) {
            log.error("支付回调幂等 Redis 不可用，已降级放行处理: identifier={}", identifier, e);
            return true;
        }
    }

    public void clearAlipayNotifySeen(String tradeNo, String outTradeNo) {
        String identifier = tradeNo == null || tradeNo.isBlank() ? outTradeNo : tradeNo;
        if (identifier == null || identifier.isBlank()) {
            return;
        }
        try {
            redisTemplate.delete("payment:notify:" + identifier);
        } catch (Exception e) {
            log.warn("清除支付回调幂等键失败（可忽略）: identifier={}", identifier, e);
        }
    }

    private String stringValue(Object value) {
        return value == null ? "" : String.valueOf(value).trim();
    }

    private boolean asBoolean(Object value) {
        if (value instanceof Boolean b) {
            return b;
        }
        return Boolean.parseBoolean(String.valueOf(value));
    }

    private long asLong(Object value) {
        if (value == null || String.valueOf(value).isBlank()) {
            return 0L;
        }
        return Long.parseLong(String.valueOf(value));
    }

    private String amountSignString(Object value) {
        java.math.BigDecimal amount = com.modstore.util.MoneyUtils.parse(value).stripTrailingZeros();
        if (amount.scale() <= 0) {
            return amount.toPlainString();
        }
        return amount.toPlainString();
    }
}
