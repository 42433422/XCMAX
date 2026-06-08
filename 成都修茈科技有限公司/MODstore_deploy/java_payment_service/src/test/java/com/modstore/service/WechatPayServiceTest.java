package com.modstore.service;

import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;

import java.math.BigDecimal;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

class WechatPayServiceTest {

    @Test
    void configured_requiresAllFields() {
        WechatPayService s = new WechatPayService();
        setAll(s, "a", "m", "/key.pem", "serial", "apiv3keyapiv3keyapiv3keyapiv3key", "https://x/notify");
        assertThat(s.configured()).isTrue();

        WechatPayService partial = new WechatPayService();
        setAll(partial, "a", "", "/key.pem", "serial", "apiv3keyapiv3keyapiv3keyapiv3key", "https://x/notify");
        assertThat(partial.configured()).isFalse();
    }

    @Test
    void createNativePay_returnsNotConfiguredWhenIncomplete() {
        WechatPayService s = new WechatPayService();
        Map<String, Object> r = s.createNativePay("o1", "subj", BigDecimal.ONE);
        assertThat(r.get("ok")).isEqualTo(false);
        assertThat(String.valueOf(r.get("message"))).contains("未配置");
    }

    private static void setAll(
            WechatPayService s,
            String appId,
            String mchId,
            String keyPath,
            String serial,
            String apiV3,
            String notify
    ) {
        ReflectionTestUtils.setField(s, "appId", appId);
        ReflectionTestUtils.setField(s, "mchId", mchId);
        ReflectionTestUtils.setField(s, "privateKeyPath", keyPath);
        ReflectionTestUtils.setField(s, "merchantSerialNo", serial);
        ReflectionTestUtils.setField(s, "apiV3Key", apiV3);
        ReflectionTestUtils.setField(s, "notifyUrl", notify);
    }
}
