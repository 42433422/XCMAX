package com.modstore.util;

/**
 * 与 {@link com.modstore.config.AlipayConfig} 中密钥处理保持一致：
 * {@link com.alipay.api.DefaultAlipayClient} 使用规范化后的「支付宝公钥」，
 * 异步通知 {@link com.alipay.api.internal.util.AlipaySignature#rsaCheckV1} 也必须使用同一规范化结果，
 * 否则在环境变量含 PEM 头尾、字面量 {@code \n}、首尾空白时会出现「查单验签失败 / 通知验签失败」不一致或双失败。
 */
public final class AlipayKeyNormalizer {

    private AlipayKeyNormalizer() {
    }

    public static String normalize(String key) {
        if (key == null) {
            return "";
        }
        String s = stripOuterQuotes(key)
                .replace("\\n", "\n")
                .replace("\r\n", "\n")
                .replace("\r", "\n")
                .trim();
        if (s.startsWith("\ufeff")) {
            s = s.substring(1).trim();
        }
        s = s
                .replace("-----BEGIN RSA PRIVATE KEY-----", "")
                .replace("-----END RSA PRIVATE KEY-----", "")
                .replace("-----BEGIN PRIVATE KEY-----", "")
                .replace("-----END PRIVATE KEY-----", "")
                .replace("-----BEGIN PUBLIC KEY-----", "")
                .replace("-----END PUBLIC KEY-----", "");
        return s.replaceAll("\\s+", "");
    }

    private static String stripOuterQuotes(String value) {
        if (value == null) {
            return "";
        }
        String s = value.trim();
        if (s.length() >= 2) {
            char first = s.charAt(0);
            char last = s.charAt(s.length() - 1);
            if ((first == '\'' || first == '"') && first == last) {
                return s.substring(1, s.length() - 1).trim();
            }
        }
        return s;
    }
}
