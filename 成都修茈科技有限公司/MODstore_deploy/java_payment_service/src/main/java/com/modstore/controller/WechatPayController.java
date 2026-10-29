package com.modstore.controller;

import com.modstore.service.OrderService;
import com.wechat.pay.java.core.exception.ValidationException;
import org.springframework.http.HttpHeaders;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.RequestHeader;
import com.modstore.service.WechatPayService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.math.BigDecimal;
import java.util.Map;

@Slf4j
@RestController
@RequestMapping("/api/payment/notify")
@RequiredArgsConstructor
public class WechatPayController {

    private final WechatPayService wechatPayService;
    private final OrderService orderService;

    @PostMapping("/wechat")
    public ResponseEntity<Map<String, Object>> wechatNotify(
            @RequestBody String body, @RequestHeader HttpHeaders headers) {
        try {
            Map<String, Object> plain = wechatPayService.verifyNotification(body,
                    singleHeader(headers, "Wechatpay-Serial", true),
                    singleHeader(headers, "Wechatpay-Nonce", true),
                    singleHeader(headers, "Wechatpay-Signature", true),
                    singleHeader(headers, "Wechatpay-Timestamp", true),
                    singleHeader(headers, "Wechatpay-Signature-Type", false));
            String outTradeNo = String.valueOf(plain.getOrDefault("out_trade_no", ""));
            String tradeState = String.valueOf(plain.getOrDefault("trade_state", ""));
            String transactionId = String.valueOf(plain.getOrDefault("transaction_id", ""));
            BigDecimal amount = parsePayerTotal(plain.get("amount"));
            orderService.processWechatNotify(outTradeNo, tradeState, transactionId, amount);
            return ResponseEntity.ok(Map.of("code", "SUCCESS", "message", "成功"));
        } catch (ValidationException | IllegalArgumentException e) {
            log.warn("微信支付通知被拒绝: {}", e.getClass().getSimpleName());
            return ResponseEntity.status(401).body(Map.of("code", "FAIL", "message", "通知验证失败"));
        } catch (RuntimeException e) {
            log.error("微信支付通知处理未完成: {}", e.getClass().getSimpleName());
            return ResponseEntity.status(500).body(Map.of("code", "FAIL", "message", "通知处理失败"));
        }
    }

    private String singleHeader(HttpHeaders headers, String name, boolean required) {
        var values = headers.get(name);
        if (values == null || values.isEmpty()) {
            if (required) throw new IllegalArgumentException("missing notification header");
            return "";
        }
        if (values.size() != 1 || values.get(0).isBlank()) {
            throw new IllegalArgumentException("ambiguous notification header");
        }
        return values.get(0);
    }

    @SuppressWarnings("unchecked")
    private BigDecimal parsePayerTotal(Object raw) {
        if (!(raw instanceof Map<?, ?> amountMap)) {
            return null;
        }
        Object payerTotal = ((Map<String, Object>) amountMap).get("payer_total");
        if (payerTotal == null) {
            payerTotal = ((Map<String, Object>) amountMap).get("total");
        }
        if (payerTotal == null) {
            return null;
        }
        return new BigDecimal(String.valueOf(payerTotal)).movePointLeft(2).setScale(2);
    }
}
