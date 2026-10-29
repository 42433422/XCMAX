package com.modstore.controller;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.modstore.service.OrderService;
import com.modstore.service.WechatPayService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.request.MockHttpServletRequestBuilder;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import javax.crypto.Cipher;
import javax.crypto.spec.GCMParameterSpec;
import javax.crypto.spec.SecretKeySpec;
import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.KeyPair;
import java.security.KeyPairGenerator;
import java.security.Signature;
import java.time.Instant;
import java.util.Base64;
import java.util.Map;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/** Real SDK RSA/GCM and HTTP entrypoint; generated keys, no provider calls. */
class WechatNotificationVerificationTest {
    @TempDir Path temporary;
    private static final String KEY = "0123456789abcdef0123456789abcdef";
    private static final String KEY_ID = "PUB_KEY_ID_AUDIT_SYNTHETIC";
    private static final String NONCE = "audit-notification-nonce";
    private final ObjectMapper mapper = new ObjectMapper();
    private KeyPair keys;
    private OrderService orders;
    private MockMvc mvc;

    @BeforeEach
    void setup() throws Exception {
        KeyPairGenerator generator = KeyPairGenerator.getInstance("RSA");
        generator.initialize(2048);
        keys = generator.generateKeyPair();
        Path publicKey = temporary.resolve("synthetic-public.pem");
        Files.writeString(publicKey, "-----BEGIN PUBLIC KEY-----\n"
                + Base64.getMimeEncoder(64, new byte[]{'\n'}).encodeToString(keys.getPublic().getEncoded())
                + "\n-----END PUBLIC KEY-----\n");
        WechatPayService service = new WechatPayService();
        ReflectionTestUtils.setField(service, "platformPublicKeyPath", publicKey.toString());
        ReflectionTestUtils.setField(service, "platformPublicKeyId", KEY_ID);
        ReflectionTestUtils.setField(service, "apiV3Key", KEY);
        ReflectionTestUtils.setField(service, "appId", "audit-app");
        ReflectionTestUtils.setField(service, "mchId", "audit-merchant");
        orders = mock(OrderService.class);
        mvc = MockMvcBuilders.standaloneSetup(new WechatPayController(service, orders)).build();
    }

    private String body(String merchant) throws Exception {
        String plain = mapper.writeValueAsString(Map.of(
                "appid", "audit-app", "mchid", merchant, "out_trade_no", "AUDIT-ORDER",
                "trade_state", "SUCCESS", "transaction_id", "AUDIT-TRANSACTION",
                "amount", Map.of("total", 500, "payer_total", 500, "currency", "CNY")));
        String nonce = "abcdefghijkl";
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.ENCRYPT_MODE, new SecretKeySpec(KEY.getBytes(StandardCharsets.UTF_8), "AES"),
                new GCMParameterSpec(128, nonce.getBytes(StandardCharsets.UTF_8)));
        cipher.updateAAD("transaction".getBytes(StandardCharsets.UTF_8));
        String encrypted = Base64.getEncoder().encodeToString(cipher.doFinal(plain.getBytes(StandardCharsets.UTF_8)));
        return mapper.writeValueAsString(Map.of(
                "id", "audit-event", "create_time", Instant.now().toString(),
                "event_type", "TRANSACTION.SUCCESS", "resource_type", "encrypt-resource",
                "resource", Map.of("algorithm", "AEAD_AES_256_GCM", "nonce", nonce,
                        "associated_data", "transaction", "ciphertext", encrypted)));
    }

    private MockHttpServletRequestBuilder request(String body, long timestamp) throws Exception {
        String time = Long.toString(timestamp);
        Signature signer = Signature.getInstance("SHA256withRSA");
        signer.initSign(keys.getPrivate());
        signer.update((time + "\n" + NONCE + "\n" + body + "\n").getBytes(StandardCharsets.UTF_8));
        return post("/api/payment/notify/wechat").contentType("application/json").content(body)
                .header("Wechatpay-Serial", KEY_ID).header("Wechatpay-Nonce", NONCE)
                .header("Wechatpay-Timestamp", time)
                .header("Wechatpay-Signature", Base64.getEncoder().encodeToString(signer.sign()));
    }

    @Test void authenticNotificationReachesBusiness() throws Exception {
        mvc.perform(request(body("audit-merchant"), Instant.now().getEpochSecond())).andExpect(status().isOk());
        verify(orders).processWechatNotify("AUDIT-ORDER", "SUCCESS", "AUDIT-TRANSACTION", new BigDecimal("5.00"));
    }

    @Test void modifiedRawBodyIsRejected() throws Exception {
        String original = body("audit-merchant");
        mvc.perform(request(original, Instant.now().getEpochSecond()).content(original + " "))
                .andExpect(status().isUnauthorized());
        verifyNoInteractions(orders);
    }

    @Test void wrongMerchantIsRejectedAfterAuthenticSignature() throws Exception {
        mvc.perform(request(body("another-merchant"), Instant.now().getEpochSecond()))
                .andExpect(status().isUnauthorized());
        verifyNoInteractions(orders);
    }

    @Test void expiredAndFutureNotificationsAreRejected() throws Exception {
        long now = Instant.now().getEpochSecond();
        for (long offset : new long[]{-600, 600}) {
            mvc.perform(request(body("audit-merchant"), now + offset)).andExpect(status().isUnauthorized());
        }
        verifyNoInteractions(orders);
    }

    @Test void missingOrAmbiguousHeadersCannotReachBusiness() throws Exception {
        mvc.perform(post("/api/payment/notify/wechat").contentType("application/json").content(body("audit-merchant")))
                .andExpect(status().isUnauthorized());
        mvc.perform(request(body("audit-merchant"), Instant.now().getEpochSecond()).header("Wechatpay-Serial", "OTHER"))
                .andExpect(status().isUnauthorized());
        verifyNoInteractions(orders);
    }

    @Test void unsupportedSignatureTypeIsRejected() throws Exception {
        mvc.perform(request(body("audit-merchant"), Instant.now().getEpochSecond()).header("Wechatpay-Signature-Type", "NONE"))
                .andExpect(status().isUnauthorized());
        verifyNoInteractions(orders);
    }

    @Test void businessFailureDoesNotReturnSuccessfulAcknowledgement() throws Exception {
        doThrow(new IllegalStateException("synthetic transaction failure")).when(orders)
                .processWechatNotify(anyString(), anyString(), anyString(), any());
        mvc.perform(request(body("audit-merchant"), Instant.now().getEpochSecond())).andExpect(status().isInternalServerError());
    }
}
