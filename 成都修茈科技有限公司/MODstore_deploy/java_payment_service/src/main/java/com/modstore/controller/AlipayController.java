package com.modstore.controller;

import com.modstore.service.AlipayService;
import com.modstore.service.OrderService;
import com.modstore.service.PaymentMetrics;
import com.modstore.service.SecurityService;
import com.modstore.util.MoneyUtils;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import jakarta.servlet.http.HttpServletRequest;
import java.util.Enumeration;
import java.util.HashMap;
import java.util.Map;

@Slf4j
@RestController
@RequestMapping("/api/payment/notify")
@RequiredArgsConstructor
public class AlipayController {
    
    private final AlipayService alipayService;
    private final OrderService orderService;
    private final SecurityService securityService;
    private final PaymentMetrics paymentMetrics;
    
    @PostMapping("/alipay")
    public String alipayNotify(HttpServletRequest request) {
        try {
            // 获取所有请求参数
            Map<String, String> params = new HashMap<>();
            Enumeration<String> parameterNames = request.getParameterNames();
            while (parameterNames.hasMoreElements()) {
                String name = parameterNames.nextElement();
                String value = request.getParameter(name);
                params.put(name, value);
            }
            
            log.info("收到支付宝通知: out_trade_no={}, trade_status={}", 
                    params.get("out_trade_no"), params.get("trade_status"));
            
            // 验签
            if (!alipayService.verifyNotify(params)) {
                log.warn("支付宝通知验签失败");
                paymentMetrics.recordNotify("alipay", "verify_failed");
                return "fail";
            }
            
            // 处理通知
            String outTradeNo = params.get("out_trade_no");
            String tradeStatus = params.get("trade_status");
            String tradeNo = params.get("trade_no");
            String buyerId = params.get("buyer_id");
            String totalAmount = params.get("total_amount");
            
            if (outTradeNo == null) {
                log.warn("支付宝通知缺少out_trade_no");
                paymentMetrics.recordNotify("alipay", "missing_out_trade_no");
                return "fail";
            }
            
            // 处理支付成功的通知
            if ("TRADE_SUCCESS".equals(tradeStatus) || "TRADE_FINISHED".equals(tradeStatus)) {
                if (!securityService.markAlipayNotifySeen(tradeNo, outTradeNo)) {
                    log.info("支付宝通知已处理，跳过: out_trade_no={}, trade_no={}", outTradeNo, tradeNo);
                    paymentMetrics.recordNotify("alipay", "duplicate");
                    return "success";
                }
                try {
                    orderService.processAlipayNotify(outTradeNo, tradeStatus, tradeNo, buyerId, MoneyUtils.parse(totalAmount));
                } catch (RuntimeException e) {
                    securityService.clearAlipayNotifySeen(tradeNo, outTradeNo);
                    paymentMetrics.recordNotify("alipay", "process_failed");
                    throw e;
                }
                log.info("支付宝通知处理成功: out_trade_no={}", outTradeNo);
                paymentMetrics.recordNotify("alipay", "success");
            } else {
                paymentMetrics.recordNotify("alipay", "ignored_status");
            }
            
            return "success";
        } catch (Exception e) {
            log.error("处理支付宝通知失败", e);
            paymentMetrics.recordNotify("alipay", "exception");
            return "fail";
        }
    }
}
