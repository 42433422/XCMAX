package com.modstore.controller;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.modstore.model.Entitlement;
import com.modstore.model.Order;
import com.modstore.model.PlanTemplate;
import com.modstore.model.Quota;
import com.modstore.model.Transaction;
import com.modstore.model.User;
import com.modstore.model.UserPlan;
import com.modstore.service.AlipayService;
import com.modstore.service.CurrentUserService;
import com.modstore.service.EntitlementService;
import com.modstore.service.OrderService;
import com.modstore.service.PaymentMetrics;
import com.modstore.service.SecurityService;
import com.modstore.service.WalletService;
import com.modstore.service.WechatPayService;
import com.modstore.repository.PlanTemplateRepository;
import com.modstore.repository.UserPlanRepository;
import com.modstore.util.MoneyUtils;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;

import java.math.BigDecimal;
import java.util.*;

@Slf4j
@RestController
@RequestMapping("/api/payment")
@RequiredArgsConstructor
public class PaymentController {
    
    private final OrderService orderService;
    private final AlipayService alipayService;
    private final SecurityService securityService;
    private final CurrentUserService currentUserService;
    private final PlanTemplateRepository planTemplateRepository;
    private final UserPlanRepository userPlanRepository;
    private final EntitlementService entitlementService;
    private final WalletService walletService;
    private final WechatPayService wechatPayService;
    private final PaymentMetrics paymentMetrics;
    private final ObjectMapper objectMapper = new ObjectMapper();

    /** 任一 SVIP 档（含 svip 入门档）算"已是 SVIP"。 */
    private static final Set<String> SVIP_TIER_PLAN_IDS = Set.of(
            "plan_enterprise",
            "plan_svip2", "plan_svip3", "plan_svip4",
            "plan_svip5", "plan_svip6", "plan_svip7", "plan_svip8"
    );

    /** 需要"先成为 SVIP"才能购买的进阶档。 */
    private static final Set<String> SVIP_LOCKED_PLAN_IDS = Set.of(
            "plan_svip2", "plan_svip3", "plan_svip4",
            "plan_svip5", "plan_svip6", "plan_svip7", "plan_svip8"
    );

    /** 与 Python payment_api、前端会员页一致；值越大档越高。 */
    private static final Map<String, Integer> MEMBERSHIP_TIER_ORDER = Map.ofEntries(
            Map.entry("plan_basic", 0),
            Map.entry("plan_pro", 1),
            Map.entry("plan_enterprise", 2),
            Map.entry("plan_svip2", 3),
            Map.entry("plan_svip3", 4),
            Map.entry("plan_svip4", 5),
            Map.entry("plan_svip5", 6),
            Map.entry("plan_svip6", 7),
            Map.entry("plan_svip7", 8),
            Map.entry("plan_svip8", 9)
    );

    @Value("${payment.public-origin}")
    private String publicOrigin;

    @Value("${payment.market-prefix}")
    private String marketPrefix;
    
    @GetMapping("/plans")
    public Map<String, Object> getPlans() {
        List<Map<String, Object>> plans = planTemplateRepository.findByActiveTrue().stream()
                .sorted(Comparator
                        .<PlanTemplate, Integer>comparing(p -> MEMBERSHIP_TIER_ORDER.getOrDefault(
                                p.getId(), Integer.MAX_VALUE))
                        .thenComparing(PlanTemplate::getId, String::compareTo))
                .map(this::planToMap)
                .toList();
        return Map.of("plans", plans);
    }

    @PostMapping("/sign-checkout")
    public Map<String, Object> signCheckout(@RequestBody Map<String, Object> request) {
        User user = currentUserService.requireCurrentUser();
        try {
            enforceSvipGate(request, user);
            enforceNotLowerPlanThanCurrent(request, user);
            Map<String, Object> resolved = orderService.resolveCheckoutFields(request, user);
            resolved.put("request_id", securityService.generateRequestId());
            resolved.put("timestamp", System.currentTimeMillis() / 1000);
            resolved.put("signature", securityService.signCheckout(resolved));
            return resolved;
        } catch (IllegalArgumentException e) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, e.getMessage());
        }
    }
    
    @PostMapping("/checkout")
    public Map<String, Object> checkout(@RequestBody Map<String, Object> request) {
        String payChannel = String.valueOf(request.getOrDefault("pay_channel", "alipay"));
        try {
            String requestId = (String) request.get("request_id");
            Long timestamp = Long.valueOf(String.valueOf(request.get("timestamp")));
            String signature = (String) request.get("signature");
            
            if (securityService.checkReplayAttack(requestId, timestamp)) {
                paymentMetrics.recordCheckout(payChannel, false, "replay");
                return Map.of("ok", false, "message", "请求已过期或重复");
            }
            
            if (!securityService.verifySignature(request, signature)) {
                paymentMetrics.recordCheckout(payChannel, false, "bad_signature");
                return Map.of("ok", false, "message", "签名验证失败");
            }

            User user = currentUserService.requireCurrentUser();
            enforceSvipGate(request, user);
            enforceNotLowerPlanThanCurrent(request, user);
            Map<String, Object> resolved = orderService.resolveCheckoutFields(request, user);
            String subject = String.valueOf(resolved.get("subject"));
            BigDecimal totalAmount = MoneyUtils.parse(resolved.get("total_amount"));
            String orderKind = String.valueOf(resolved.get("order_kind"));
            long itemIdRaw = MoneyUtils.asLong(resolved.get("item_id"));
            Long itemId = itemIdRaw > 0 ? itemIdRaw : null;
            String planId = String.valueOf(resolved.get("plan_id"));
            String outTradeNo = "MOD" + System.currentTimeMillis() + user.getId();

            Order order = orderService.createOrder(
                    user, outTradeNo, subject, totalAmount, orderKind,
                    itemId,
                    planId.isBlank() || "null".equalsIgnoreCase(planId) ? null : planId,
                    requestId
            );

            String returnUrl = checkoutReturnUrl(outTradeNo);
            Map<String, Object> payResult;
            if ("wechat".equals(payChannel)) {
                if (!wechatPayService.configured()) {
                    orderService.updateOrderStatus(outTradeNo, "failed", null, null, null);
                    paymentMetrics.recordCheckout(payChannel, false, "wechat_not_configured");
                    return Map.of("ok", false, "message", "微信支付未配置，请选择支付宝或联系管理员");
                }
                payResult = wechatPayService.createNativePay(outTradeNo, subject, totalAmount);
            } else {
                // 仅走电脑网站支付 alipay.trade.page.pay，需在开放平台开通「电脑网站支付」；
                // 不调用 wap / 当面付 precreate，避免未开通相应产品时接口权限不足。
                payResult = alipayService.createPagePay(outTradeNo, subject, totalAmount, returnUrl);
            }
            
            if (Boolean.TRUE.equals(payResult.get("ok"))) {
                orderService.updatePaymentMetadata(
                        order.getOutTradeNo(),
                        String.valueOf(payResult.get("type")),
                        payResult.get("qr_code") == null ? null : String.valueOf(payResult.get("qr_code"))
                );
                paymentMetrics.recordCheckout(payChannel, true, "created");
                return Map.of(
                    "ok", true,
                    "order_id", outTradeNo,
                    "type", payResult.get("type"),
                    "redirect_url", payResult.getOrDefault("redirect_url", ""),
                    "qr_code", payResult.getOrDefault("qr_code", ""),
                    "subject", subject,
                    "total_amount", totalAmount.toPlainString()
                );
            } else {
                orderService.updateOrderStatus(outTradeNo, "failed", null, null, null);
                Object rawMsg = payResult.get("message");
                String failMsg =
                        rawMsg == null || String.valueOf(rawMsg).isBlank()
                                ? "支付下单失败（无详细说明）"
                                : String.valueOf(rawMsg).trim();
                paymentMetrics.recordCheckout(payChannel, false, "provider_failed");
                return Map.of("ok", false, "message", failMsg);
            }
        } catch (IllegalArgumentException e) {
            log.warn("下单参数校验失败: {}", e.getMessage());
            paymentMetrics.recordCheckout(payChannel, false, "validation");
            return Map.of("ok", false, "message", e.getMessage());
        } catch (Exception e) {
            log.error("下单失败", e);
            paymentMetrics.recordCheckout(payChannel, false, "exception");
            return Map.of("ok", false, "message", "系统内部错误");
        }
    }
    
    @GetMapping("/query/{outTradeNo}")
    public Map<String, Object> queryOrder(
            @PathVariable String outTradeNo,
            @RequestParam(value = "reconcile", defaultValue = "false") boolean reconcile) {
        try {
            Optional<Order> optionalOrder = orderService.findByOutTradeNo(outTradeNo);
            if (optionalOrder.isEmpty()) {
                return Map.of("ok", false, "message", "订单不存在");
            }
            
            Order order = optionalOrder.get();
            User user = currentUserService.requireCurrentUser();
            if (!user.isAdmin() && !order.getUser().getId().equals(user.getId())) {
                return Map.of("ok", false, "message", "无权查看该订单");
            }
            if (reconcile) {
                try {
                    orderService.reconcileWithAlipayIfUnfulfilled(outTradeNo);
                } catch (Exception e) {
                    log.warn("订单对账异常(忽略): outTradeNo={} {}", outTradeNo, e.getMessage());
                }
                optionalOrder = orderService.findByOutTradeNo(outTradeNo);
                if (optionalOrder.isEmpty()) {
                    return Map.of("ok", false, "message", "订单不存在");
                }
                order = optionalOrder.get();
            }
            return orderToMap(order);
        } catch (Exception e) {
            log.error("查询订单失败", e);
            return Map.of("ok", false, "message", "系统内部错误");
        }
    }
    
    @GetMapping("/orders")
    public Map<String, Object> listOrders(
            @RequestParam(required = false) String status,
            @RequestParam(defaultValue = "50") int limit,
            @RequestParam(defaultValue = "0") int offset
    ) {
        try {
            User user = currentUserService.requireCurrentUser();
            String normalizedStatus = normalizeStatus(status);
            List<Order> orders = orderService.findByUser(user, normalizedStatus, limit, offset);
            long total = orderService.countByUser(user, normalizedStatus);
            List<Map<String, Object>> orderList = orders.stream().map(this::orderToMap).toList();
            return Map.of("orders", orderList, "total", total);
        } catch (Exception e) {
            log.error("获取订单列表失败", e);
            return Map.of("ok", false, "message", "系统内部错误");
        }
    }

    /**
     * 从「我的订单」中隐藏已关闭/失败/已退款等非进行中记录；待支付、已支付、退款中 不处理。不删库。
     */
    @PostMapping("/orders/dismiss-non-active")
    public Map<String, Object> dismissNonActiveOrders() {
        try {
            User user = currentUserService.requireCurrentUser();
            int n = orderService.dismissNonActiveOrdersForUser(user);
            return Map.of("ok", true, "dismissed", n);
        } catch (Exception e) {
            log.error("清理订单展示失败", e);
            return Map.of("ok", false, "message", e.getMessage() == null ? "系统内部错误" : e.getMessage());
        }
    }

    @PostMapping("/cancel/{outTradeNo}")
    public Map<String, Object> cancelOrder(@PathVariable String outTradeNo) {
        User user = currentUserService.requireCurrentUser();
        boolean closed = orderService.cancelPendingOrder(user, outTradeNo);
        return Map.of("ok", closed, "status", closed ? "closed" : "unchanged");
    }

    @GetMapping("/diagnostics")
    public Map<String, Object> diagnostics() {
        User user = currentUserService.requireCurrentUser();
        Map<String, Object> result = new HashMap<>();
        result.put("ok", true);
        result.put("service", "java_payment_service");
        result.put("alipay_configured", true);
        result.put("wechatpay_configured", wechatPayService.configured());
        result.put("database", "postgresql");
        result.put("redis", "required_for_replay_protection");
        Map<String, Object> notifyDiag = new HashMap<>(alipayService.notifyUrlDiagnostics());
        if (!user.isAdmin()) {
            notifyDiag.remove("effective_notify_url");
        }
        result.put("alipay_async_notify", notifyDiag);
        result.put(
                "payment_notify_chain",
                "支付宝 POST -> 公网 Nginx :443 -> Python /api/payment/* -> (PAYMENT_BACKEND=java) 转发 Java :8080 /api/payment/notify/alipay"
        );
        return result;
    }

    /**
     * 管理员：为历史已支付、已履约的会员单补发随单「按实付价取整元」入金；有幂等流水则跳过。需经网关到 Java（与 /api/payment 同路）。
     */
    @PostMapping("/reconcile/membership-tokens-backfill")
    public Map<String, Object> reconcileMembershipTokensBackfill() {
        User user = currentUserService.requireCurrentUser();
        if (!user.isAdmin()) {
            return Map.of("ok", false, "message", "需要管理员权限");
        }
        try {
            return orderService.backfillPlanMembershipTokenGrants();
        } catch (Exception e) {
            log.warn("membership backfill: {}", e.getMessage());
            return Map.of("ok", false, "message", e.getMessage());
        }
    }

    @GetMapping("/entitlements")
    public Map<String, Object> entitlements() {
        User user = currentUserService.requireCurrentUser();
        List<Map<String, Object>> rows = entitlementService.getActiveEntitlements(user).stream()
                .map(this::entitlementToMap)
                .toList();
        return Map.of("entitlements", rows, "items", rows, "total", rows.size());
    }

    @GetMapping("/usage-metrics")
    public Map<String, Object> usageMetrics() {
        return Map.of(
                "total_calls", 0,
                "success_rate", 0,
                "total_tokens", 0,
                "avg_duration_ms", 0,
                "rows", List.of()
        );
    }

    @PostMapping("/refund")
    public Map<String, Object> refund(@RequestBody Map<String, Object> request) {
        User user = currentUserService.requireCurrentUser();
        if (!user.isAdmin()) {
            return Map.of("ok", false, "message", "需要管理员权限");
        }
        return Map.of("ok", false, "message", "退款已统一到钱包资金中心，请使用 /api/refunds 申请和审核");
    }

    @GetMapping("/my-plan")
    public Map<String, Object> myPlan() {
        User user = currentUserService.requireCurrentUser();
        Optional<UserPlan> activePlan = entitlementService.getActivePlan(user);
        List<Map<String, Object>> quotas = entitlementService.getQuotas(user).stream()
                .map(this::quotaToMap)
                .toList();
        Map<String, Object> result = new HashMap<>();
        Map<String, Object> membership = activePlan.map(this::membershipToMap).orElseGet(() -> membershipToMap(null));
        result.put("plan", activePlan.map(this::userPlanToMap).orElse(null));
        result.put("membership", membership);
        result.put("quotas", quotas);
        return result;
    }

    private String checkoutReturnUrl(String outTradeNo) {
        String prefix = marketPrefix == null ? "/market" : marketPrefix.trim();
        if (!prefix.startsWith("/")) {
            prefix = "/" + prefix;
        }
        while (prefix.endsWith("/") && prefix.length() > 1) {
            prefix = prefix.substring(0, prefix.length() - 1);
        }
        String origin = publicOrigin == null ? "" : publicOrigin.trim();
        while (origin.endsWith("/")) {
            origin = origin.substring(0, origin.length() - 1);
        }
        return origin + prefix + "/checkout/" + outTradeNo;
    }

    private Map<String, Object> orderToMap(Order order) {
        Map<String, Object> result = new HashMap<>();
        result.put("out_trade_no", order.getOutTradeNo());
        result.put("trade_no", order.getTradeNo());
        result.put("status", order.getStatus());
        result.put("subject", order.getSubject());
        result.put("total_amount", order.getTotalAmount() == null ? "0.00" : order.getTotalAmount().toPlainString());
        result.put("created_at", order.getCreatedAt());
        result.put("updated_at", order.getUpdatedAt());
        result.put("paid_at", order.getPaidAt());
        result.put("fulfilled", order.isFulfilled());
        result.put("refunded_amount", order.getRefundedAmount() == null ? "0.00" : order.getRefundedAmount().toPlainString());
        result.put("refund_status", order.getRefundStatus());
        result.put("refunded_at", order.getRefundedAt());
        result.put("order_kind", order.getOrderKind());
        result.put("item_id", order.getItemId() == null ? 0 : order.getItemId());
        result.put("plan_id", order.getPlanId() == null ? "" : order.getPlanId());
        result.put("qr_code", order.getQrCode());
        result.put("pay_type", order.getPayType());
        result.put("wallet_transactions", walletService.getTransactionsForOrder(order.getUser(), order.getOutTradeNo()).stream()
                .map(this::transactionToMap)
                .toList());
        return result;
    }

    private Map<String, Object> transactionToMap(Transaction transaction) {
        Map<String, Object> row = new HashMap<>();
        row.put("id", transaction.getId());
        row.put("amount", transaction.getAmount());
        row.put("txn_type", transaction.getTransactionType());
        row.put("type", transaction.getTransactionType());
        row.put("status", transaction.getStatus());
        row.put("description", transaction.getDescription());
        row.put("reference_no", transaction.getReferenceNo());
        row.put("order_no", transaction.getOrderNo());
        row.put("refund_no", transaction.getRefundNo());
        row.put("balance_before", transaction.getBalanceBefore());
        row.put("balance_after", transaction.getBalanceAfter());
        row.put("created_at", transaction.getCreatedAt());
        return row;
    }

    private Map<String, Object> planToMap(PlanTemplate plan) {
        Map<String, Object> row = new HashMap<>();
        row.put("id", plan.getId());
        row.put("name", plan.getName());
        row.put("description", plan.getDescription());
        row.put("price", plan.getPrice());
        try {
            row.put("features", objectMapper.readValue(plan.getFeaturesJson(), new TypeReference<List<String>>() {}));
        } catch (Exception e) {
            row.put("features", List.of());
        }
        // FE 用此字段判断是否需要"购买 svip 后解锁"
        row.put("requires_plan", SVIP_LOCKED_PLAN_IDS.contains(plan.getId()) ? "plan_enterprise" : null);
        return row;
    }

    /** 当前用户是否拥有任一 SVIP 档（含 svip 入门档）；用于 SVIP2~SVIP8 购买前置校验。 */
    private boolean userOwnsAnySvipTier(User user) {
        return userPlanRepository.findFirstByUserAndActiveTrueOrderByStartedAtDesc(user)
                .map(up -> up.getPlan() != null && up.getPlan().getId() != null
                        && SVIP_TIER_PLAN_IDS.contains(up.getPlan().getId()))
                .orElse(false);
    }

    /** 校验下单的 plan_id：SVIP2~SVIP8 必须先持有 svip 入门档。 */
    private void enforceSvipGate(Map<String, Object> request, User user) {
        Object pidObj = request.get("plan_id");
        String planId = pidObj == null ? "" : String.valueOf(pidObj).trim();
        if (planId.isEmpty()) return;
        if (!SVIP_LOCKED_PLAN_IDS.contains(planId)) return;
        if (!userOwnsAnySvipTier(user)) {
            throw new IllegalArgumentException("需要先购买 svip 档后才能购买 SVIP2~SVIP8");
        }
    }

    private int userMaxKnownMembershipOrder(User user) {
        return userPlanRepository.findByUserAndActiveTrue(user).stream()
                .mapToInt(up -> {
                    if (up.getPlan() == null || up.getPlan().getId() == null) {
                        return -1;
                    }
                    return MEMBERSHIP_TIER_ORDER.getOrDefault(up.getPlan().getId().trim(), -1);
                })
                .max()
                .orElse(-1);
    }

    /** 已拥更高档时不得再购买低档位套餐。 */
    private void enforceNotLowerPlanThanCurrent(Map<String, Object> request, User user) {
        Object pidObj = request.get("plan_id");
        String planId = pidObj == null ? "" : String.valueOf(pidObj).trim();
        if (planId.isEmpty() || "null".equalsIgnoreCase(planId)) {
            return;
        }
        if (!MEMBERSHIP_TIER_ORDER.containsKey(planId)) {
            return;
        }
        int tNew = MEMBERSHIP_TIER_ORDER.get(planId);
        int tCur = userMaxKnownMembershipOrder(user);
        if (tCur >= 0 && tNew < tCur) {
            throw new IllegalArgumentException("已拥有更高等级会员，不能购买此低档套餐");
        }
    }

    private Map<String, Object> entitlementToMap(Entitlement entitlement) {
        Map<String, Object> row = new HashMap<>();
        row.put("id", entitlement.getId());
        row.put("catalog_id", entitlement.getCatalogId());
        row.put("entitlement_type", entitlement.getEntitlementType());
        row.put("source_order_id", entitlement.getSourceOrderId());
        row.put("metadata_json", entitlement.getMetadataJson());
        row.put("granted_at", entitlement.getGrantedAt());
        row.put("expires_at", entitlement.getExpiresAt());
        return row;
    }

    private Map<String, Object> userPlanToMap(UserPlan userPlan) {
        Map<String, Object> row = new HashMap<>(membershipToMap(userPlan));
        row.put("id", userPlan.getPlan().getId());
        row.put("name", userPlan.getPlan().getName());
        row.put("started_at", userPlan.getStartedAt());
        row.put("expires_at", userPlan.getExpiresAt() == null ? "" : userPlan.getExpiresAt());
        return row;
    }

    private Map<String, Object> membershipToMap(UserPlan userPlan) {
        String planId = userPlan == null || userPlan.getPlan() == null ? "" : userPlan.getPlan().getId();
        Map<String, Object> row = new HashMap<>();
        row.put("is_member", !planId.isBlank());
        // VIP+ 起开放 BYOK
        row.put("can_byok",
                "plan_pro".equals(planId)
                || "plan_enterprise".equals(planId)
                || SVIP_LOCKED_PLAN_IDS.contains(planId));
        String tier;
        String label;
        switch (planId) {
            case "plan_basic" -> { tier = "vip";      label = "VIP"; }
            case "plan_pro" -> { tier = "vip_plus"; label = "VIP+"; }
            case "plan_enterprise" -> { tier = "svip1";    label = "svip"; }
            case "plan_svip2" -> { tier = "svip2";    label = "SVIP2"; }
            case "plan_svip3" -> { tier = "svip3";    label = "SVIP3"; }
            case "plan_svip4" -> { tier = "svip4";    label = "SVIP4"; }
            case "plan_svip5" -> { tier = "svip5";    label = "SVIP5"; }
            case "plan_svip6" -> { tier = "svip6";    label = "SVIP6"; }
            case "plan_svip7" -> { tier = "svip7";    label = "SVIP7"; }
            case "plan_svip8" -> { tier = "svip8";    label = "SVIP8"; }
            default -> { tier = "free";     label = "普通用户"; }
        }
        row.put("tier", tier);
        row.put("label", label);
        return row;
    }

    private Map<String, Object> quotaToMap(Quota quota) {
        int remaining = Math.max(quota.getTotal() - quota.getUsed(), 0);
        return Map.of(
                "quota_type", quota.getQuotaType(),
                "total", quota.getTotal(),
                "used", quota.getUsed(),
                "remaining", remaining,
                "reset_at", quota.getResetAt() == null ? "" : quota.getResetAt()
        );
    }

    private String normalizeStatus(String status) {
        if (status == null || status.isBlank()) {
            return null;
        }
        return status.trim();
    }
}
