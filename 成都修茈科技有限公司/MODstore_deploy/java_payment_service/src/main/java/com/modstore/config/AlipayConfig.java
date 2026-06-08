package com.modstore.config;

import com.alipay.api.AlipayClient;
import com.alipay.api.DefaultAlipayClient;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.core.env.Environment;
import com.modstore.util.AlipayKeyNormalizer;
import lombok.extern.slf4j.Slf4j;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Locale;

@Configuration
@Slf4j
public class AlipayConfig {
    
    @Value("${alipay.app-id}")
    private String appId;
    
    @Value("${alipay.private-key}")
    private String privateKey;

    @Value("${alipay.private-key-path:}")
    private String privateKeyPath;
    
    @Value("${alipay.public-key}")
    private String publicKey;

    @Value("${alipay.public-key-path:}")
    private String publicKeyPath;

    @Value("${alipay.gateway-url:}")
    private String gatewayUrlOverride;

    @Value("${alipay.sandbox-gateway-url:https://openapi-sandbox.dl.alipaydev.com/gateway.do}")
    private String sandboxGatewayUrl;
    
    /**
     * 沙箱网关须与沙箱 APPID、沙箱「支付宝公钥」、应用私钥成对；{@code ALIPAY_DEBUG=1/true} 走沙箱网关。
     * 环境变量 {@code 0/1} 须可靠解析（避免与正式密钥混用导致同步返回验签失败）。
     */
    static boolean resolveAlipaySandbox(Environment env) {
        for (String key : new String[] {"ALIPAY_DEBUG", "alipay.debug"}) {
            String v = env.getProperty(key);
            if (v == null) {
                continue;
            }
            v = v.trim().toLowerCase(Locale.ROOT);
            if (v.isEmpty()) {
                continue;
            }
            if (v.equals("1") || v.equals("true") || v.equals("yes") || v.equals("on")) {
                return true;
            }
            if (v.equals("0") || v.equals("false") || v.equals("no") || v.equals("off")) {
                return false;
            }
        }
        return false;
    }

    @Bean
    public AlipayClient alipayClient(Environment env) {
        boolean debug = resolveAlipaySandbox(env);
        String override = gatewayUrlOverride == null ? "" : gatewayUrlOverride.trim();
        String serverUrl;
        if (!override.isEmpty()) {
            serverUrl = override;
        } else if (debug) {
            serverUrl = sandboxGatewayUrl == null || sandboxGatewayUrl.isBlank()
                    ? "https://openapi-sandbox.dl.alipaydev.com/gateway.do"
                    : sandboxGatewayUrl.trim();
        } else {
            serverUrl = "https://openapi.alipay.com/gateway.do";
        }

        String appPrivate = resolveKey(privateKey, privateKeyPath);
        String alipayPk = resolveKey(publicKey, publicKeyPath);
        if (appPrivate.isBlank()) {
            log.warn("支付宝应用私钥为空：请设置 ALIPAY_APP_PRIVATE_KEY 或 ALIPAY_PRIVATE_KEY（或 *_PATH）");
        }
        if (alipayPk.isBlank()) {
            log.warn("支付宝公钥为空：请设置 ALIPAY_ALIPAY_PUBLIC_KEY 或 ALIPAY_PUBLIC_KEY（或 *_PATH）。"
                    + "须为开放平台「查看支付宝公钥」中的 RSA2 公钥，不是「应用公钥」。");
        } else {
            log.info("支付宝网关: {} (sandbox={}), APP_ID 前缀: {}, 支付宝公钥长度(去空白后): {}",
                    serverUrl,
                    debug,
                    appId == null || appId.length() < 6 ? appId : appId.substring(0, 6) + "...",
                    alipayPk.length());
        }

        // 开放平台示例多为小写 json / utf-8；与部分环境下验签实现更一致
        return new DefaultAlipayClient(
            serverUrl,
            appId,
            appPrivate,
            "json",
            "utf-8",
            alipayPk,
            "RSA2"
        );
    }

    private String resolveKey(String inlineKey, String keyPath) {
        String raw = stripOuterQuotes(inlineKey);
        if (raw == null || raw.isBlank()) {
            raw = readKeyFile(stripOuterQuotes(keyPath));
        }
        return AlipayKeyNormalizer.normalize(raw);
    }

    private String readKeyFile(String keyPath) {
        if (keyPath == null || keyPath.isBlank()) {
            return "";
        }
        Path p = Path.of(keyPath.replace("\\", "/"));
        if (!p.isAbsolute()) {
            p = Path.of(System.getProperty("user.dir")).resolve(p).normalize();
        }
        try {
            return Files.readString(p, StandardCharsets.UTF_8);
        } catch (IOException e) {
            log.warn("无法读取支付宝密钥文件: {}", p);
            return "";
        }
    }

    private String stripOuterQuotes(String value) {
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
