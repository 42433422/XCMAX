package com.modstore.service;

import org.junit.jupiter.api.Test;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ValueOperations;
import org.springframework.test.util.ReflectionTestUtils;

import java.time.Duration;
import java.util.HashMap;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

class SecurityServiceTest {

    @Test
    void signsAndVerifiesCanonicalCheckoutPayload() {
        SecurityService service = newService(mock(StringRedisTemplate.class));
        Map<String, Object> data = new HashMap<>();
        data.put("plan_id", "plan_basic");
        data.put("item_id", 0);
        data.put("total_amount", "9.90");
        data.put("subject", "基础版 MOD");
        data.put("wallet_recharge", false);
        data.put("request_id", "req-1");
        data.put("timestamp", 1710000000);
        data.put("signature", "ignored");

        String signature = service.signCheckout(data);

        assertTrue(service.verifySignature(data, signature));
        assertTrue(service.verifySignature(data, signature.toUpperCase()));
        assertFalse(service.verifySignature(data, "bad-signature"));
    }

    @Test
    void replayProtectionUsesRedisSetIfAbsentWithTtl() {
        StringRedisTemplate redisTemplate = mock(StringRedisTemplate.class);
        @SuppressWarnings("unchecked")
        ValueOperations<String, String> valueOps = mock(ValueOperations.class);
        when(redisTemplate.opsForValue()).thenReturn(valueOps);
        when(valueOps.setIfAbsent(eq("payment:nonce:req-1"), eq("1"), any(Duration.class))).thenReturn(true);
        SecurityService service = newService(redisTemplate);

        assertFalse(service.checkReplayAttack("req-1", System.currentTimeMillis() / 1000));
        verify(valueOps).setIfAbsent(eq("payment:nonce:req-1"), eq("1"), any(Duration.class));
    }

    @Test
    void checkReplay_treatsStaleTimestampAsAttack() {
        StringRedisTemplate redis = mock(StringRedisTemplate.class);
        SecurityService service = newService(redis);
        long ts = (System.currentTimeMillis() / 1000) - 400;
        assertTrue(service.checkReplayAttack("r-stale", ts));
        verifyNoInteractions(redis);
    }

    @Test
    void checkReplay_treatsBlankRequestIdAsAttack() {
        StringRedisTemplate redis = mock(StringRedisTemplate.class);
        SecurityService service = newService(redis);
        assertTrue(service.checkReplayAttack("  ", System.currentTimeMillis() / 1000));
        assertTrue(service.checkReplayAttack(null, System.currentTimeMillis() / 1000));
    }

    @Test
    void checkReplay_treatsDuplicateRequestIdAsAttack() {
        StringRedisTemplate redisTemplate = mock(StringRedisTemplate.class);
        @SuppressWarnings("unchecked")
        ValueOperations<String, String> valueOps = mock(ValueOperations.class);
        when(redisTemplate.opsForValue()).thenReturn(valueOps);
        when(valueOps.setIfAbsent(eq("payment:nonce:dup-req"), eq("1"), any(Duration.class)))
                .thenReturn(false);
        SecurityService service = newService(redisTemplate);
        assertTrue(service.checkReplayAttack("dup-req", System.currentTimeMillis() / 1000));
    }

    @Test
    void checkReplay_allowsRequestWhenRedisUnavailable() {
        StringRedisTemplate redisTemplate = mock(StringRedisTemplate.class);
        @SuppressWarnings("unchecked")
        ValueOperations<String, String> valueOps = mock(ValueOperations.class);
        when(redisTemplate.opsForValue()).thenReturn(valueOps);
        when(valueOps.setIfAbsent(anyString(), anyString(), any(Duration.class)))
                .thenThrow(new RuntimeException("redis down"));
        SecurityService service = newService(redisTemplate);
        assertFalse(service.checkReplayAttack("degraded", System.currentTimeMillis() / 1000));
    }

    @Test
    void markAlipayNotifySeen_prefersTradeNo() {
        StringRedisTemplate redis = mock(StringRedisTemplate.class);
        @SuppressWarnings("unchecked")
        ValueOperations<String, String> valueOps = mock(ValueOperations.class);
        when(redis.opsForValue()).thenReturn(valueOps);
        when(valueOps.setIfAbsent(eq("payment:notify:trade-a"), anyString(), any(Duration.class)))
                .thenReturn(true);
        SecurityService service = newService(redis);
        assertTrue(service.markAlipayNotifySeen("trade-a", "out-ignored"));
    }

    @Test
    void markAlipayNotifySeen_fallsBackToOutTradeNo() {
        StringRedisTemplate redis = mock(StringRedisTemplate.class);
        @SuppressWarnings("unchecked")
        ValueOperations<String, String> valueOps = mock(ValueOperations.class);
        when(redis.opsForValue()).thenReturn(valueOps);
        when(valueOps.setIfAbsent(eq("payment:notify:out-1"), anyString(), any(Duration.class)))
                .thenReturn(true);
        SecurityService service = newService(redis);
        assertTrue(service.markAlipayNotifySeen("", "out-1"));
    }

    @Test
    void markAlipayNotifySeen_rejectsEmptyIdentifiers() {
        SecurityService service = newService(mock(StringRedisTemplate.class));
        assertFalse(service.markAlipayNotifySeen(null, "  "));
    }

    @Test
    void clearAlipayNotifySeen_deletesExpectedKey() {
        StringRedisTemplate redis = mock(StringRedisTemplate.class);
        SecurityService service = newService(redis);
        service.clearAlipayNotifySeen("T", "");
        verify(redis).delete("payment:notify:T");
    }

    @Test
    void verifySignatureReturnsFalseOnMalformedData() {
        StringRedisTemplate redis = mock(StringRedisTemplate.class);
        SecurityService service = newService(redis);
        assertFalse(service.verifySignature(null, "x"));
    }

    @Test
    void constantTimeEqualsHex_rejectsLengthMismatch() {
        assertFalse(SecurityService.constantTimeEqualsHex("abcd", "ab"));
        assertFalse(SecurityService.constantTimeEqualsHex("ab", "abcd"));
    }

    @Test
    void clearAlipayNotifySeen_noopsWhenIdentifierBlank() {
        StringRedisTemplate redis = mock(StringRedisTemplate.class);
        SecurityService service = newService(redis);
        service.clearAlipayNotifySeen(" ", "  ");
        verify(redis, never()).delete(anyString());
    }

    @Test
    void canonicalCheckoutHonoursBooleanTypeForWallet() {
        StringRedisTemplate redis = mock(StringRedisTemplate.class);
        SecurityService service = newService(redis);
        Map<String, Object> m = new HashMap<>();
        m.put("item_id", 0);
        m.put("plan_id", "x");
        m.put("request_id", "a");
        m.put("subject", "s");
        m.put("timestamp", 1);
        m.put("total_amount", "1");
        m.put("wallet_recharge", true);
        String sig = service.signCheckout(m);
        m.put("signature", sig);
        m.put("wallet_recharge", Boolean.TRUE);
        assertTrue(service.verifySignature(m, sig));
    }

    @Test
    void markAlipayNotifySeen_allowsProcessingWhenRedisUnavailable() {
        StringRedisTemplate redis = mock(StringRedisTemplate.class);
        @SuppressWarnings("unchecked")
        ValueOperations<String, String> valueOps = mock(ValueOperations.class);
        when(redis.opsForValue()).thenReturn(valueOps);
        when(valueOps.setIfAbsent(anyString(), anyString(), any(Duration.class)))
                .thenThrow(new RuntimeException("redis down"));
        SecurityService service = newService(redis);
        assertTrue(service.markAlipayNotifySeen("t1", "out-1"));
    }

    private SecurityService newService(StringRedisTemplate redisTemplate) {
        SecurityService service = new SecurityService(redisTemplate);
        ReflectionTestUtils.setField(service, "paymentSecretKey", "test-payment-secret");
        return service;
    }
}
