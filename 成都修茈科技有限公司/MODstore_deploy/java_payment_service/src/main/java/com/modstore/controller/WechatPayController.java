package com.modstore.controller;

import com.modstore.service.OrderService;
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
    public Map<String, Object> wechatNotify(@RequestBody Map<String, Object> body) {
        try {
            Map<String, Object> plain = wechatPayService.decryptNotify(body);
            String outTradeNo = String.valueOf(plain.getOrDefault("out_trade_no", ""));
            String tradeState = String.valueOf(plain.getOrDefault("trade_state", ""));
            String transactionId = String.valueOf(plain.getOrDefault("transaction_id", ""));
            BigDecimal amount = parsePayerTotal(plain.get("amount"));
            orderService.processWechatNotify(outTradeNo, tradeState, transactionId, amount);
            return Map.of("code", "SUCCESS", "message", "成功");
        } catch (Exception e) {
            log.error("处理微信支付通知失败", e);
            return Map.of("code", "FAIL", "message", e.getMessage());
        }
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
