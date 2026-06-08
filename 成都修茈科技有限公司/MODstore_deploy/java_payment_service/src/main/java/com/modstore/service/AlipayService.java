package com.modstore.service;

import com.alipay.api.AlipayApiException;
import com.alipay.api.AlipayClient;
import com.alipay.api.AlipayResponse;
import com.alipay.api.request.AlipayTradePagePayRequest;
import com.alipay.api.request.AlipayTradePrecreateRequest;
import com.alipay.api.request.AlipayTradeQueryRequest;
import com.alipay.api.request.AlipayTradeWapPayRequest;
import com.alipay.api.response.AlipayTradePagePayResponse;
import com.alipay.api.response.AlipayTradePrecreateResponse;
import com.alipay.api.response.AlipayTradeQueryResponse;
import com.alipay.api.response.AlipayTradeWapPayResponse;
import com.alipay.api.internal.util.AlipaySignature;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.modstore.util.AlipayKeyNormalizer;
import com.modstore.util.MoneyUtils;
import jakarta.annotation.PostConstruct;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.HashMap;
import java.util.Map;
import java.util.TreeMap;
import java.util.Locale;
import java.util.StringJoiner;

@Slf4j
@Service
@RequiredArgsConstructor
public class AlipayService {

    private final AlipayClient alipayClient;
    private final ObjectMapper objectMapper;
    private final HttpClient httpClient = HttpClient.newBuilder().build();

    @Value("${alipay.app-id}")
    private String appId;

    @Value("${alipay.private-key}")
    private String alipayPrivateKey;

    @Value("${alipay.gateway-url:}")
    private String gatewayUrlOverride;

    @Value("${alipay.sandbox-gateway-url:https://openapi-sandbox.dl.alipaydev.com/gateway.do}")
    private String sandboxGatewayUrl;

    @Value("${alipay.debug:false}")
    private String alipayDebug;

    @Value("${alipay.public-key}")
    private String alipayPublicKey;

    /** 与 {@link com.alipay.api.DefaultAlipayClient} 使用同一套规范化逻辑，避免仅通知验签失败。 */
    private String alipayPublicKeyNormalized;
    private String alipayPrivateKeyNormalized;
    private String alipayGatewayUrl;

    @Value("${alipay.notify-url:}")
    private String notifyUrl;

    @PostConstruct
    void prepareAlipayKeys() {
        alipayPublicKeyNormalized = AlipayKeyNormalizer.normalize(alipayPublicKey);
        alipayPrivateKeyNormalized = AlipayKeyNormalizer.normalize(alipayPrivateKey);
        alipayGatewayUrl = resolveGatewayUrl();
    }

    @PostConstruct
    void warnIfAsyncNotifyMissing() {
        if (notifyUrl == null || notifyUrl.isBlank()) {
            log.warn(
                    "ALIPAY_NOTIFY_URL 未配置：支付宝下单请求将不包含 notify_url，付款成功后支付宝异步通知不会发到本服务。"
                            + " 请设为公网可访问的 https://<域名>/api/payment/notify/alipay ，并保证 Nginx 将 /api/ 反代到本机后由 Python 再转发到 Java（PAYMENT_BACKEND=java）。"
            );
        } else {
            String n = notifyUrl.trim();
            if (n.contains("127.0.0.1") || n.toLowerCase().contains("localhost")) {
                log.warn("ALIPAY_NOTIFY_URL 指向本机地址，支付宝外网无法访问，异步通知将永远到不了: {}", n);
            } else if (!n.startsWith("https://")) {
                log.warn("ALIPAY_NOTIFY_URL 非 https，生产环境支付宝可能无法回调: {}", n);
            }
        }
    }

    /**
     * 供 /api/payment/diagnostics 展示：不返回私钥，仅帮助确认异步通知是否可能到达。
     */
    public Map<String, Object> notifyUrlDiagnostics() {
        Map<String, Object> m = new HashMap<>();
        String nu = notifyUrl == null ? "" : notifyUrl.trim();
        boolean configured = !nu.isBlank();
        m.put("configured", configured);
        if (!configured) {
            m.put("severity", "error");
            m.put(
                    "hint",
                    "未设置 ALIPAY_NOTIFY_URL：trade 请求不带 notify_url，支付宝服务器无法 POST 异步通知；仅靠前端轮询 reconcile 对账。"
            );
            return m;
        }
        m.put("effective_notify_url", nu);
        boolean https = nu.startsWith("https://");
        boolean localhost = nu.contains("127.0.0.1") || nu.toLowerCase().contains("localhost");
        String pathNorm = nu.replaceAll("/+$", "");
        boolean pathOk = pathNorm.endsWith("/api/payment/notify/alipay")
                || nu.contains("/api/payment/notify/alipay?");
        m.put("https", https);
        m.put("reachable_from_internet", https && !localhost);
        m.put("path_ok", pathOk);
        if (localhost) {
            m.put("severity", "error");
            m.put("hint", "支付宝无法访问 127.0.0.1/localhost，请改为公网域名 + HTTPS");
        } else if (!https) {
            m.put("severity", "warning");
            m.put("hint", "生产环境回调地址建议使用 https://");
        } else if (!pathOk) {
            m.put("severity", "warning");
            m.put("hint", "路径应为 https://<域名>/api/payment/notify/alipay 与 SecurityConfig 白名单一致");
        } else {
            m.put("severity", "ok");
        }
        return m;
    }

    private String bizContentJson(Map<String, Object> bizContent) {
        try {
            return objectMapper.writeValueAsString(bizContent);
        } catch (JsonProcessingException e) {
            throw new IllegalStateException("支付宝 biz_content 序列化失败", e);
        }
    }

    private void applyNotifyUrl(AlipayTradePagePayRequest request) {
        if (notifyUrl != null && !notifyUrl.isBlank()) {
            request.setNotifyUrl(notifyUrl.trim());
        }
    }

    private void applyNotifyUrl(AlipayTradeWapPayRequest request) {
        if (notifyUrl != null && !notifyUrl.isBlank()) {
            request.setNotifyUrl(notifyUrl.trim());
        }
    }

    private void applyNotifyUrl(AlipayTradePrecreateRequest request) {
        if (notifyUrl != null && !notifyUrl.isBlank()) {
            request.setNotifyUrl(notifyUrl.trim());
        }
    }

    private static String firstNonBlank(String... parts) {
        if (parts == null) {
            return null;
        }
        for (String p : parts) {
            if (p != null && !p.isBlank()) {
                return p.trim();
            }
        }
        return null;
    }

    /** 网关返回 isSuccess=false 时的可读说明（sub_msg/msg/code 常有一个非空）。 */
    private static String alipayResponseFailureMessage(AlipayResponse r) {
        if (r == null) {
            return "支付宝无有效响应";
        }
        String line = firstNonBlank(r.getSubMsg(), r.getMsg());
        if (line != null) {
            return truncate(line, 240);
        }
        String code = firstNonBlank(r.getSubCode(), r.getCode());
        if (code != null) {
            return truncate("支付宝返回码: " + code, 240);
        }
        return "支付宝拒绝下单（无 sub_msg/msg，请查服务端日志）";
    }

    /**
     * SDK 抛 AlipayApiException 时的用户可见说明。
     * 部分环境（TLS/代理/密钥格式）下 getErrMsg/getMessage 可能为空，需串联 cause 与 errCode。
     */
    /**
     * 支付宝/SDK 常返回「支付请求失败」等笼统句；补充固定排查提示，避免前端只显示半句。
     */
    private static String enrichGenericAlipayMessage(String line) {
        if (line == null || line.isBlank()) {
            return line;
        }
        String t = line.trim();
        boolean vague = t.length() <= 32
                && (t.contains("支付请求失败") || t.contains("系统繁忙") || t.contains("系统异常") || t.contains("未知错误"));
        if (!vague) {
            return line;
        }
        return t + " — 请核对：ALIPAY_APP_ID；应用 RSA2 私钥与支付宝公钥（路径或内容）；ALIPAY_DEBUG 与沙箱/正式是否一致；"
                + "服务器能否访问支付宝网关；以及 Java 日志中的 AlipayApiException 堆栈。";
    }

    private static String alipayExceptionUserMessage(AlipayApiException e) {
        String direct = firstNonBlank(e.getErrMsg(), e.getMessage());
        if (direct != null) {
            String low = direct.toLowerCase();
            if (low.contains("私钥") && (low.contains("invalidkey") || low.contains("format") || low.contains("rs"))) {
                return "应用私钥无法被 SDK 用于 RSA2 签名。请用开放平台「接口加签方式」中与本应用成对的**应用私钥**原样上传服务器"
                        + " `keys/app_private_key.pem`（可 PEM 或去头尾的单行 base64，勿手打漏字）；在服务器上可用"
                        + " `openssl pkey -in app_private_key.pem -text -noout` 或 DER 解出后校验。原始："
                        + truncate(direct.trim(), 180);
            }
            if (low.contains("sign check") || low.contains("sign and data")) {
                return "支付宝同步返回验签失败：① ALIPAY_ALIPAY_PUBLIC_KEY / ALIPAY_PUBLIC_KEY 必须是开放平台"
                        + "「支付宝公钥」(RSA2)，不能填「应用公钥」；② 正式环境须 ALIPAY_DEBUG=0 且 APPID、"
                        + "应用私钥、支付宝公钥均为正式；沙箱须 ALIPAY_DEBUG=1 且三者均为沙箱；③ 密钥 PEM 勿含 BOM。"
                        + " 原始信息：" + truncate(direct.trim(), 160);
            }
            return enrichGenericAlipayMessage(truncate(direct, 240));
        }
        String code = e.getErrCode();
        if (code != null && !code.isBlank()) {
            return truncate("支付宝错误码: " + code.trim(), 240);
        }
        Throwable c = e.getCause();
        while (c != null) {
            String cm = c.getMessage();
            if (cm != null && !cm.isBlank()) {
                return enrichGenericAlipayMessage(truncate(cm.trim(), 240));
            }
            c = c.getCause();
        }
        return "支付请求失败：未取到支付宝错误详情。请核对 ALIPAY_APP_ID、RSA2 私钥与支付宝公钥、ALIPAY_DEBUG、"
                + "ALIPAY_NOTIFY_URL 以及服务器到 openapi 的网络；并查看 Java 日志。";
    }

    private static String truncate(String s, int max) {
        return s.length() <= max ? s : s.substring(0, max) + "…";
    }

    /**
     * SDK 内部可能用 RuntimeException/InvocationTargetException 包装 {@link AlipayApiException}，仅 catch 其类型会漏掉，导致控制层只返回「系统内部错误」。
     */
    private static AlipayApiException findAlipayApiException(Throwable t) {
        for (Throwable c = t; c != null; c = c.getCause()) {
            if (c instanceof AlipayApiException) {
                return (AlipayApiException) c;
            }
        }
        return null;
    }

    private static boolean isSignCheckFailure(Throwable t) {
        for (Throwable c = t; c != null; c = c.getCause()) {
            String msg = c.getMessage();
            if (msg != null) {
                String low = msg.toLowerCase(Locale.ROOT);
                if (low.contains("sign check fail") || low.contains("check sign and data fail")) {
                    return true;
                }
            }
        }
        return false;
    }

    private void putAlipayExecuteError(Map<String, Object> result, String logMessage, Exception e) {
        AlipayApiException alipay = findAlipayApiException(e);
        if (alipay != null) {
            log.error(logMessage, e);
            result.put("ok", false);
            result.put("message", alipayExceptionUserMessage(alipay));
        } else {
            log.error(logMessage + "（非 AlipayApiException）", e);
            result.put("ok", false);
            result.put("message", truncate("支付失败：" + (e.getMessage() == null || e.getMessage().isBlank()
                    ? e.getClass().getSimpleName()
                    : e.getMessage()), 220));
        }
    }

    public Map<String, Object> createPagePay(String outTradeNo, String subject, BigDecimal totalAmount, String returnUrl) {
        Map<String, Object> result = new HashMap<>();
        AlipayTradePagePayRequest pagePayRequest = new AlipayTradePagePayRequest();
        applyNotifyUrl(pagePayRequest);
        try {
            pagePayRequest.setReturnUrl(returnUrl);

            Map<String, Object> bizContent = new TreeMap<>();
            bizContent.put("out_trade_no", outTradeNo);
            bizContent.put("product_code", "FAST_INSTANT_TRADE_PAY");
            bizContent.put("subject", subject);
            bizContent.put("total_amount", MoneyUtils.alipayTotalAmount(totalAmount));

            pagePayRequest.setBizContent(bizContentJson(bizContent));
            // GET：getBody() 为完整跳转 URL，前端 window.location 可用；默认 POST 为 HTML 表单，勿当 URL 用。
            AlipayTradePagePayResponse response = alipayClient.pageExecute(pagePayRequest, "GET");

            if (response.isSuccess()) {
                result.put("ok", true);
                result.put("type", "page");
                result.put("redirect_url", response.getBody());
            } else {
                result.put("ok", false);
                result.put("message", alipayResponseFailureMessage(response));
            }
        } catch (Exception e) {
            putAlipayExecuteError(result, "支付宝PC支付失败", e);
        }
        return result;
    }

    public Map<String, Object> createWapPay(String outTradeNo, String subject, BigDecimal totalAmount, String returnUrl, String quitUrl) {
        Map<String, Object> result = new HashMap<>();
        AlipayTradeWapPayRequest wapPayRequest = new AlipayTradeWapPayRequest();
        applyNotifyUrl(wapPayRequest);
        try {
            wapPayRequest.setReturnUrl(returnUrl);

            Map<String, Object> bizContent = new TreeMap<>();
            bizContent.put("out_trade_no", outTradeNo);
            bizContent.put("product_code", "QUICK_WAP_WAY");
            bizContent.put("subject", subject);
            bizContent.put("total_amount", MoneyUtils.alipayTotalAmount(totalAmount));
            if (quitUrl != null && !quitUrl.isBlank()) {
                bizContent.put("quit_url", quitUrl);
            }

            wapPayRequest.setBizContent(bizContentJson(bizContent));
            AlipayTradeWapPayResponse response = alipayClient.pageExecute(wapPayRequest, "GET");

            if (response.isSuccess()) {
                result.put("ok", true);
                result.put("type", "wap");
                result.put("redirect_url", response.getBody());
            } else {
                result.put("ok", false);
                result.put("message", alipayResponseFailureMessage(response));
            }
        } catch (Exception e) {
            putAlipayExecuteError(result, "支付宝手机支付失败", e);
        }
        return result;
    }

    public Map<String, Object> createPrecreatePay(String outTradeNo, String subject, BigDecimal totalAmount) {
        Map<String, Object> result = new HashMap<>();
        AlipayTradePrecreateRequest precreateRequest = new AlipayTradePrecreateRequest();
        applyNotifyUrl(precreateRequest);
        try {
            Map<String, Object> bizContent = new TreeMap<>();
            bizContent.put("out_trade_no", outTradeNo);
            bizContent.put("subject", subject);
            bizContent.put("total_amount", MoneyUtils.alipayTotalAmount(totalAmount));

            precreateRequest.setBizContent(bizContentJson(bizContent));
            AlipayTradePrecreateResponse response = alipayClient.execute(precreateRequest);

            if (response.isSuccess()) {
                result.put("ok", true);
                result.put("type", "precreate");
                result.put("qr_code", response.getQrCode());
            } else {
                result.put("ok", false);
                result.put("message", alipayResponseFailureMessage(response));
            }
        } catch (Exception e) {
            putAlipayExecuteError(result, "支付宝扫码支付失败", e);
        }
        return result;
    }

    public Map<String, Object> queryOrder(String outTradeNo) {
        Map<String, Object> result = new HashMap<>();
        AlipayTradeQueryRequest queryRequest = new AlipayTradeQueryRequest();
        try {
            Map<String, Object> bizContent = new TreeMap<>();
            bizContent.put("out_trade_no", outTradeNo);

            queryRequest.setBizContent(bizContentJson(bizContent));
            AlipayTradeQueryResponse response = alipayClient.execute(queryRequest);

            if (response.isSuccess()) {
                result.put("ok", true);
                result.put("trade_status", response.getTradeStatus());
                result.put("trade_no", response.getTradeNo());
                result.put("buyer_id", response.getBuyerUserId());
                result.put("total_amount", response.getTotalAmount());
            } else {
                result.put("ok", false);
                result.put("message", alipayResponseFailureMessage(response));
            }
        } catch (Exception e) {
            if (isSignCheckFailure(e)) {
                Map<String, Object> fallback = queryOrderWithoutResponseSignCheck(outTradeNo);
                if (Boolean.TRUE.equals(fallback.get("ok"))) {
                    log.warn("支付宝 SDK 响应验签失败，已使用 HTTPS 直连查单兜底: outTradeNo={}", outTradeNo);
                    return fallback;
                }
            }
            putAlipayExecuteError(result, "查询订单失败", e);
        }
        return result;
    }

    /**
     * 支付宝 SDK 在部分线上配置下会先拿到 code=10000/TRADE_SUCCESS，再因同步响应验签失败抛异常。
     * 为避免用户已付款却无法入账，兜底使用同一应用私钥签名并通过 HTTPS 直连官方网关查单。
     * 调用方仍会用本地订单金额二次校验后才履约。
     */
    private Map<String, Object> queryOrderWithoutResponseSignCheck(String outTradeNo) {
        Map<String, Object> result = new HashMap<>();
        if (alipayGatewayUrl == null || alipayGatewayUrl.isBlank()
                || appId == null || appId.isBlank()
                || alipayPrivateKeyNormalized == null || alipayPrivateKeyNormalized.isBlank()) {
            result.put("ok", false);
            result.put("message", "支付宝兜底查单配置不完整");
            return result;
        }
        try {
            Map<String, Object> bizContent = new TreeMap<>();
            bizContent.put("out_trade_no", outTradeNo);

            Map<String, String> params = new TreeMap<>();
            params.put("app_id", appId);
            params.put("method", "alipay.trade.query");
            params.put("format", "json");
            params.put("charset", "utf-8");
            params.put("sign_type", "RSA2");
            params.put("timestamp", LocalDateTime.now().format(DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss")));
            params.put("version", "1.0");
            params.put("biz_content", bizContentJson(bizContent));
            params.put(
                    "sign",
                    AlipaySignature.rsaSign(
                            AlipaySignature.getSignContent(params),
                            alipayPrivateKeyNormalized,
                            "utf-8",
                            "RSA2"
                    )
            );

            HttpRequest request = HttpRequest.newBuilder(URI.create(alipayGatewayUrl))
                    .header("Content-Type", "application/x-www-form-urlencoded;charset=utf-8")
                    .POST(HttpRequest.BodyPublishers.ofString(formEncode(params)))
                    .build();
            HttpResponse<String> response = httpClient.send(request, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
            Map<String, Object> root = objectMapper.readValue(response.body(), new TypeReference<>() {});
            Object body = root.get("alipay_trade_query_response");
            if (!(body instanceof Map<?, ?> raw)) {
                result.put("ok", false);
                result.put("message", "支付宝兜底查单响应格式异常");
                return result;
            }
            Map<?, ?> qr = raw;
            Object codeObj = qr.get("code");
            String code = codeObj == null ? "" : String.valueOf(codeObj);
            if (!"10000".equals(code)) {
                Object subMsg = qr.get("sub_msg");
                Object msg = qr.get("msg");
                result.put("ok", false);
                result.put("message", subMsg == null ? String.valueOf(msg) : String.valueOf(subMsg));
                return result;
            }
            result.put("ok", true);
            result.put("trade_status", qr.get("trade_status"));
            result.put("trade_no", qr.get("trade_no"));
            result.put("buyer_id", qr.get("buyer_user_id"));
            result.put("total_amount", qr.get("total_amount"));
            result.put("verify_fallback", true);
        } catch (Exception ex) {
            log.warn("支付宝 HTTPS 兜底查单失败: outTradeNo={} error={}", outTradeNo, ex.getMessage());
            result.put("ok", false);
            result.put("message", "支付宝兜底查单失败：" + (ex.getMessage() == null ? ex.getClass().getSimpleName() : ex.getMessage()));
        }
        return result;
    }

    private String resolveGatewayUrl() {
        String override = gatewayUrlOverride == null ? "" : gatewayUrlOverride.trim();
        if (!override.isEmpty()) {
            return override;
        }
        if (parseTruthy(alipayDebug)) {
            return sandboxGatewayUrl == null || sandboxGatewayUrl.isBlank()
                    ? "https://openapi-sandbox.dl.alipaydev.com/gateway.do"
                    : sandboxGatewayUrl.trim();
        }
        return "https://openapi.alipay.com/gateway.do";
    }

    private static boolean parseTruthy(String value) {
        if (value == null) {
            return false;
        }
        String v = value.trim().toLowerCase(Locale.ROOT);
        return v.equals("1") || v.equals("true") || v.equals("yes") || v.equals("on");
    }

    private static String formEncode(Map<String, String> params) {
        StringJoiner joiner = new StringJoiner("&");
        for (Map.Entry<String, String> e : params.entrySet()) {
            joiner.add(URLEncoder.encode(e.getKey(), StandardCharsets.UTF_8)
                    + "="
                    + URLEncoder.encode(e.getValue(), StandardCharsets.UTF_8));
        }
        return joiner.toString();
    }

    public boolean verifyNotify(Map<String, String> params) {
        try {
            return AlipaySignature.rsaCheckV1(params, alipayPublicKeyNormalized, "utf-8", "RSA2");
        } catch (Exception e) {
            log.error("验签失败", e);
            return false;
        }
    }
}
