package com.modstore.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.wechat.pay.java.core.RSAAutoCertificateConfig;
import com.wechat.pay.java.core.notification.NotificationConfig;
import com.wechat.pay.java.core.notification.NotificationParser;
import com.wechat.pay.java.core.notification.RequestParam;
import com.wechat.pay.java.core.notification.RSAPublicKeyNotificationConfig;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Service;
import org.springframework.web.reactive.function.client.WebClient;
import org.springframework.web.reactive.function.client.WebClientResponseException;
import org.springframework.web.util.UriUtils;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.KeyFactory;
import java.security.PrivateKey;
import java.security.Signature;
import java.security.spec.PKCS8EncodedKeySpec;
import java.time.Instant;
import java.util.Base64;
import java.util.HashMap;
import java.util.Map;
import java.util.UUID;

@Service
@RequiredArgsConstructor
public class WechatPayService {

    private final ObjectMapper objectMapper = new ObjectMapper();
    private final WebClient webClient = WebClient.builder()
            .baseUrl("https://api.mch.weixin.qq.com")
            .build();

    @Value("${wechatpay.app-id:}")
    private String appId;

    @Value("${wechatpay.mch-id:}")
    private String mchId;

    @Value("${wechatpay.private-key-path:}")
    private String privateKeyPath;

    @Value("${wechatpay.merchant-serial-no:}")
    private String merchantSerialNo;

    @Value("${wechatpay.api-v3-key:}")
    private String apiV3Key;

    @Value("${wechatpay.notify-url:}")
    private String notifyUrl;

    @Value("${wechatpay.platform-public-key-path:}")
    private String platformPublicKeyPath;

    @Value("${wechatpay.platform-public-key-id:}")
    private String platformPublicKeyId;

    private volatile NotificationParser notificationParser;

    public boolean configured() {
        return !blank(appId) && !blank(mchId) && !blank(privateKeyPath)
                && !blank(merchantSerialNo) && !blank(apiV3Key) && !blank(notifyUrl);
    }

    public Map<String, Object> createNativePay(String outTradeNo, String subject, BigDecimal amount) {
        if (!configured()) {
            return Map.of("ok", false, "message", "微信支付未配置");
        }
        try {
            Map<String, Object> amountBody = Map.of("total", amount.movePointRight(2).intValueExact(), "currency", "CNY");
            Map<String, Object> body = new HashMap<>();
            body.put("appid", appId);
            body.put("mchid", mchId);
            body.put("description", subject);
            body.put("out_trade_no", outTradeNo);
            body.put("notify_url", notifyUrl);
            body.put("amount", amountBody);
            String json = objectMapper.writeValueAsString(body);
            String path = "/v3/pay/transactions/native";
            String timestamp = String.valueOf(Instant.now().getEpochSecond());
            String nonce = UUID.randomUUID().toString().replace("-", "");
            String authorization = authorization("POST", path, timestamp, nonce, json);
            Map<String, Object> resp = webClient.post()
                    .uri(path)
                    .contentType(MediaType.APPLICATION_JSON)
                    .header("Authorization", authorization)
                    .header("Accept", "application/json")
                    .bodyValue(json)
                    .retrieve()
                    .bodyToMono(new org.springframework.core.ParameterizedTypeReference<Map<String, Object>>() {})
                    .block();
            String codeUrl = String.valueOf(resp == null ? "" : resp.getOrDefault("code_url", ""));
            if (codeUrl.isBlank()) {
                return Map.of("ok", false, "message", "微信支付未返回 code_url");
            }
            return Map.of("ok", true, "type", "wechat_native", "qr_code", codeUrl, "code_url", codeUrl);
        } catch (Exception e) {
            return Map.of("ok", false, "message", "微信支付下单失败: " + e.getMessage());
        }
    }

    /**
     * 微信 V3 查单：与异步通知未达时客户端轮询对账配合，trade_state=SUCCESS 时与 notify 同路径履约。
     * 签名串中的 URL 须与实际请求 path（含 encode）一致。
     */
    public Map<String, Object> queryTransactionByOutTradeNo(String outTradeNo) {
        if (!configured()) {
            return Map.of("ok", false, "message", "微信支付未配置");
        }
        if (blank(outTradeNo)) {
            return Map.of("ok", false, "message", "out_trade_no 为空");
        }
        try {
            String pathForSign = "/v3/pay/transactions/out-trade-no/"
                    + UriUtils.encodePath(outTradeNo, StandardCharsets.UTF_8)
                    + "?mchid="
                    + UriUtils.encodeQueryParam(mchId, StandardCharsets.UTF_8);
            String timestamp = String.valueOf(Instant.now().getEpochSecond());
            String nonce = UUID.randomUUID().toString().replace("-", "");
            String authorization = authorization("GET", pathForSign, timestamp, nonce, "");
            Map<String, Object> resp = webClient.get()
                    .uri(pathForSign)
                    .header("Authorization", authorization)
                    .header("Accept", "application/json")
                    .retrieve()
                    .bodyToMono(new org.springframework.core.ParameterizedTypeReference<Map<String, Object>>() {})
                    .block();
            if (resp == null || resp.isEmpty()) {
                return Map.of("ok", false, "message", "微信支付查单无响应");
            }
            String tradeState = String.valueOf(resp.getOrDefault("trade_state", ""));
            Map<String, Object> result = new HashMap<>();
            result.put("ok", true);
            result.put("trade_state", tradeState);
            result.put("transaction_id", resp.get("transaction_id"));
            Map<String, Object> amountMap = castMap(resp.get("amount"));
            Object payerTotal = amountMap.get("payer_total");
            if (payerTotal == null) {
                payerTotal = amountMap.get("total");
            }
            if (payerTotal != null) {
                BigDecimal yuan = new BigDecimal(String.valueOf(payerTotal)).movePointLeft(2).setScale(2, RoundingMode.HALF_UP);
                result.put("payer_total_yuan", yuan);
            }
            return result;
        } catch (WebClientResponseException e) {
            String msg = e.getResponseBodyAsString();
            if (msg != null && msg.length() > 240) {
                msg = msg.substring(0, 240);
            }
            return Map.of("ok", false, "message", "微信支付查单失败: HTTP " + e.getStatusCode().value() + " " + msg);
        } catch (Exception e) {
            return Map.of("ok", false, "message", "微信支付查单异常: " + e.getMessage());
        }
    }

    /** Verify the original bytes before parsing or applying any business effect. */
    @SuppressWarnings("unchecked")
    public Map<String, Object> verifyNotification(
            String body, String serial, String nonce, String signature, String timestamp,
            String signatureType) {
        if (blank(body) || body.length() > 1_048_576 || blank(serial) || serial.length() > 128
                || blank(nonce) || nonce.length() > 128 || blank(signature) || signature.length() > 1024
                || timestamp == null || !timestamp.matches("[0-9]{1,19}")
                || (!blank(signatureType) && !"WECHATPAY2-SHA256-RSA2048".equals(signatureType))) {
            throw new IllegalArgumentException("invalid payment notification headers");
        }
        long receivedAt = Long.parseLong(timestamp);
        long now = Instant.now().getEpochSecond();
        if (receivedAt < now - 300 || receivedAt > now + 300) {
            throw new IllegalArgumentException("payment notification outside allowed clock window");
        }
        RequestParam request = new RequestParam.Builder()
                .serialNumber(serial).nonce(nonce).signature(signature)
                .timestamp(timestamp).body(body).build();
        Map<String, Object> plain = notificationParser().parse(request, Map.class);
        if (blank(appId) || blank(mchId) || !appId.equals(plain.get("appid"))
                || !mchId.equals(plain.get("mchid"))) {
            throw new IllegalArgumentException("payment notification merchant mismatch");
        }
        return plain;
    }

    private synchronized NotificationParser notificationParser() {
        if (notificationParser != null) return notificationParser;
        NotificationConfig config;
        if (!blank(platformPublicKeyPath) || !blank(platformPublicKeyId)) {
            if (blank(platformPublicKeyPath) || blank(platformPublicKeyId)) {
                throw new IllegalStateException("both platform public key and id are required");
            }
            config = new RSAPublicKeyNotificationConfig.Builder()
                    .publicKeyFromPath(platformPublicKeyPath).publicKeyId(platformPublicKeyId)
                    .apiV3Key(apiV3Key).build();
        } else {
            // Existing certificate-mode deployments retain official rotation.
            // Cache this parser; do not download certificates for every callback.
            config = new RSAAutoCertificateConfig.Builder().merchantId(mchId)
                    .privateKeyFromPath(privateKeyPath).merchantSerialNumber(merchantSerialNo)
                    .apiV3Key(apiV3Key).build();
        }
        notificationParser = new NotificationParser(config);
        return notificationParser;
    }

    private String authorization(String method, String path, String timestamp, String nonce, String body) throws Exception {
        String message = method + "\n" + path + "\n" + timestamp + "\n" + nonce + "\n" + body + "\n";
        Signature signature = Signature.getInstance("SHA256withRSA");
        signature.initSign(loadPrivateKey());
        signature.update(message.getBytes(StandardCharsets.UTF_8));
        String signed = Base64.getEncoder().encodeToString(signature.sign());
        return "WECHATPAY2-SHA256-RSA2048 mchid=\"" + mchId
                + "\",nonce_str=\"" + nonce
                + "\",timestamp=\"" + timestamp
                + "\",serial_no=\"" + merchantSerialNo
                + "\",signature=\"" + signed + "\"";
    }

    private PrivateKey loadPrivateKey() throws Exception {
        String pem = Files.readString(Path.of(privateKeyPath), StandardCharsets.UTF_8)
                .replace("-----BEGIN PRIVATE KEY-----", "")
                .replace("-----END PRIVATE KEY-----", "")
                .replaceAll("\\s+", "");
        byte[] der = Base64.getDecoder().decode(pem);
        return KeyFactory.getInstance("RSA").generatePrivate(new PKCS8EncodedKeySpec(der));
    }

    @SuppressWarnings("unchecked")
    private Map<String, Object> castMap(Object value) {
        if (value instanceof Map<?, ?> map) {
            return (Map<String, Object>) map;
        }
        return Map.of();
    }

    private boolean blank(String value) {
        return value == null || value.trim().isEmpty();
    }
}
