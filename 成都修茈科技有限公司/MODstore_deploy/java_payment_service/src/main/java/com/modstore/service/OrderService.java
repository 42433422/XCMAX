package com.modstore.service;

import com.modstore.model.CatalogItem;
import com.modstore.model.Order;
import com.modstore.model.PlanTemplate;
import com.modstore.model.User;
import com.modstore.repository.CatalogItemRepository;
import com.modstore.repository.OrderRepository;
import com.modstore.repository.PlanTemplateRepository;
import com.modstore.repository.TransactionRepository;
import com.modstore.repository.UserRepository;
import com.modstore.util.MoneyUtils;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.data.domain.PageRequest;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionTemplate;

import java.math.BigDecimal;
import java.time.Duration;
import java.time.LocalDateTime;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

@Slf4j
@Service
@RequiredArgsConstructor
public class OrderService {
    
    private final OrderRepository orderRepository;
    private final TransactionRepository transactionRepository;
    private final UserRepository userRepository;
    private final WalletService walletService;
    private final EntitlementService entitlementService;
    private final PlanTemplateRepository planTemplateRepository;
    private final CatalogItemRepository catalogItemRepository;
    private final WebhookDispatcher webhookDispatcher;
    private final AccountLevelService accountLevelService;
    private final AlipayService alipayService;
    private final WechatPayService wechatPayService;
    private final PlatformTransactionManager transactionManager;

    private volatile TransactionTemplate lazyRequiresNewPaidCommitTemplate;

    private TransactionTemplate requiresNewPaidCommitTemplate() {
        TransactionTemplate local = lazyRequiresNewPaidCommitTemplate;
        if (local == null) {
            synchronized (this) {
                local = lazyRequiresNewPaidCommitTemplate;
                if (local == null) {
                    local = new TransactionTemplate(transactionManager);
                    local.setPropagationBehavior(TransactionDefinition.PROPAGATION_REQUIRES_NEW);
                    lazyRequiresNewPaidCommitTemplate = local;
                }
            }
        }
        return local;
    }
    
    @Transactional
    public Order createOrder(User user, String outTradeNo, String subject, BigDecimal totalAmount,
                             String orderKind, Long itemId, String planId, String requestId) {
        if (AccountLicensePlans.isAccountLicense(planId)
                && !user.isAdmin()
                && !"active".equalsIgnoreCase(user.getAccountState())) {
            user.setAccountState("pending_payment");
            userRepository.save(user);
        }
        Order order = new Order();
        order.setUser(user);
        order.setOutTradeNo(outTradeNo);
        order.setSubject(subject);
        order.setTotalAmount(totalAmount);
        order.setOrderKind(orderKind);
        order.setItemId(itemId);
        order.setPlanId(planId);
        order.setStatus("pending");
        order.setFulfilled(false);
        order.setRequestId(requestId);
        
        return orderRepository.save(order);
    }

    @Transactional(readOnly = true)
    public Map<String, Object> resolveCheckoutFields(Map<String, Object> request, User checkoutUser) {
        Map<String, Object> resolved = new HashMap<>();
        boolean walletRecharge = Boolean.parseBoolean(String.valueOf(request.getOrDefault("wallet_recharge", false)));
        BigDecimal totalAmount = MoneyUtils.parse(request.get("total_amount"));
        String subject = String.valueOf(request.getOrDefault("subject", "")).trim();
        String planId = String.valueOf(request.getOrDefault("plan_id", "")).trim();
        Long itemId = asLong(request.get("item_id"));

        if (walletRecharge) {
            if (totalAmount.compareTo(BigDecimal.ZERO) <= 0) {
                throw new IllegalArgumentException("请填写大于 0 的充值金额");
            }
            resolved.put("order_kind", "wallet");
            resolved.put("subject", subject.isBlank() ? "XC AGI 钱包充值" : subject);
            resolved.put("total_amount", totalAmount);
            resolved.put("plan_id", "");
            resolved.put("item_id", 0L);
            resolved.put("wallet_recharge", true);
            return resolved;
        }

        if (!planId.isBlank()) {
            PlanTemplate plan = planTemplateRepository.findById(planId)
                    .filter(PlanTemplate::isActive)
                    .orElseThrow(() -> new IllegalArgumentException("套餐不存在"));
            resolved.put("order_kind", "plan");
            resolved.put("subject", plan.getName());
            resolved.put("total_amount", plan.getPrice());
            resolved.put("plan_id", plan.getId());
            resolved.put("item_id", 0L);
            resolved.put("wallet_recharge", false);
            return resolved;
        }

        if (itemId != null && itemId > 0) {
            CatalogItem item = catalogItemRepository.findById(itemId)
                    .orElseThrow(() -> new IllegalArgumentException("商品不存在"));
            if (checkoutUser != null
                    && entitlementService.hasPurchasedOrActiveEntitlement(checkoutUser, item.getId())) {
                throw new IllegalArgumentException("您已购买过该商品，无需重复支付");
            }
            if (item.getPrice().compareTo(BigDecimal.ZERO) <= 0) {
                throw new IllegalArgumentException("免费商品，无需支付");
            }
            resolved.put("order_kind", "item");
            resolved.put("subject", item.getName());
            resolved.put("total_amount", item.getPrice());
            resolved.put("plan_id", "");
            resolved.put("item_id", item.getId());
            resolved.put("wallet_recharge", false);
            return resolved;
        }

        throw new IllegalArgumentException("请使用 wallet_recharge、plan_id 或 item_id 之一下单");
    }
    
    @Transactional(readOnly = true)
    public Optional<Order> findByOutTradeNo(String outTradeNo) {
        return orderRepository.findByOutTradeNo(outTradeNo);
    }
    
    @Transactional(readOnly = true)
    public Optional<Order> findByTradeNo(String tradeNo) {
        return orderRepository.findByTradeNo(tradeNo);
    }
    
    @Transactional(readOnly = true)
    public List<Order> findByUser(User user, String status, int limit, int offset) {
        int pageSize = Math.max(1, Math.min(limit, 200));
        int page = Math.max(offset, 0) / pageSize;
        return orderRepository.findVisibleByUserAndOptionalStatus(
                user, status, PageRequest.of(page, pageSize));
    }
    
    @Transactional(readOnly = true)
    public long countByUser(User user, String status) {
        return orderRepository.countVisibleByUserAndOptionalStatus(user, status);
    }

    @Transactional(readOnly = true)
    public List<Order> findAllForAdmin(User admin, String status, int limit, int offset) {
        requireAdmin(admin);
        int pageSize = Math.max(1, Math.min(limit, 500));
        int page = Math.max(offset, 0) / pageSize;
        String normalized = status == null || status.isBlank() ? null : status.trim().toLowerCase();
        return orderRepository.findAllByOptionalStatus(normalized, PageRequest.of(page, pageSize));
    }

    @Transactional(readOnly = true)
    public long countAllForAdmin(User admin, String status) {
        requireAdmin(admin);
        String normalized = status == null || status.isBlank() ? null : status.trim().toLowerCase();
        return orderRepository.countAllByOptionalStatus(normalized);
    }

    @Transactional
    public Order cancelPendingOrderAsAdmin(User admin, String outTradeNo, String reason) {
        requireAdmin(admin);
        Order order = orderRepository.findByOutTradeNoForUpdate(outTradeNo)
                .orElseThrow(() -> new IllegalArgumentException("订单不存在"));
        if (!"pending".equals(order.getStatus())) {
            throw new IllegalArgumentException("只能取消待支付订单");
        }
        closeProviderBeforeMutation(order);
        order.setStatus("closed");
        log.info("admin cancelled pending order outTradeNo={} adminId={} reason={}", outTradeNo, admin.getId(), reason);
        return orderRepository.save(order);
    }

    @Transactional
    public Map<String, Object> repricePendingOrderAsAdmin(
            User admin,
            String outTradeNo,
            BigDecimal newAmount,
            String reason,
            String returnUrl
    ) {
        requireAdmin(admin);
        if (newAmount == null || newAmount.compareTo(BigDecimal.ZERO) <= 0) {
            throw new IllegalArgumentException("新金额必须大于 0");
        }
        Order original = orderRepository.findByOutTradeNoForUpdate(outTradeNo)
                .orElseThrow(() -> new IllegalArgumentException("订单不存在"));
        if (!"pending".equals(original.getStatus())) {
            throw new IllegalArgumentException("已支付或终态订单不允许改价，请走退款审核");
        }
        if (original.getTotalAmount().compareTo(newAmount) == 0) {
            throw new IllegalArgumentException("新金额与原金额相同");
        }
        closeProviderBeforeMutation(original);
        String replacementNo = "ADJ" + System.currentTimeMillis() + admin.getId();
        Order replacement = createOrder(
                original.getUser(),
                replacementNo,
                original.getSubject(),
                newAmount,
                original.getOrderKind(),
                original.getItemId(),
                original.getPlanId(),
                "admin-reprice-" + replacementNo
        );
        Map<String, Object> pay = alipayService.createPagePay(
                replacementNo,
                replacement.getSubject(),
                newAmount,
                returnUrl
        );
        original.setStatus("closed");
        orderRepository.save(original);
        if (!Boolean.TRUE.equals(pay.get("ok"))) {
            replacement.setStatus("failed");
            orderRepository.save(replacement);
            Map<String, Object> failed = new HashMap<>();
            failed.put("ok", false);
            failed.put("partial_success", true);
            failed.put("status", "replacement_failed");
            failed.put("original_order_no", outTradeNo);
            failed.put("replacement_order", replacement);
            failed.put("message", "原支付单已安全关闭，但新金额支付单创建失败：" + pay.get("message"));
            return failed;
        }
        updatePaymentMetadata(
                replacementNo,
                String.valueOf(pay.getOrDefault("type", "page")),
                pay.get("qr_code") == null ? null : String.valueOf(pay.get("qr_code"))
        );
        log.info("admin repriced order original={} replacement={} adminId={} reason={}", outTradeNo, replacementNo, admin.getId(), reason);
        Map<String, Object> result = new HashMap<>();
        result.put("ok", true);
        result.put("status", "replaced");
        result.put("original_order_no", outTradeNo);
        result.put("replacement_order", replacement);
        result.put("redirect_url", pay.getOrDefault("redirect_url", ""));
        result.put("qr_code", pay.getOrDefault("qr_code", ""));
        return result;
    }

    private void requireAdmin(User user) {
        if (user == null || !user.isAdmin()) {
            throw new IllegalArgumentException("需要管理员权限");
        }
    }

    private void closeProviderBeforeMutation(Order order) {
        String payType = order.getPayType() == null ? "" : order.getPayType().toLowerCase();
        if (payType.contains("wechat")) {
            throw new IllegalArgumentException("微信待支付单需先完成微信支付关单，本次未改动订单");
        }
        if (!payType.isBlank() || order.getQrCode() != null) {
            Map<String, Object> closed = alipayService.closeOrder(order.getOutTradeNo());
            if (!Boolean.TRUE.equals(closed.get("ok"))) {
                throw new IllegalArgumentException("支付宝关单失败，本次未改动订单：" + closed.get("message"));
            }
        }
    }

    @Transactional(readOnly = true)
    public List<Order> findPaidValueEvidenceSince(
            LocalDateTime since,
            int limit,
            int offset
    ) {
        int pageSize = Math.max(1, Math.min(limit, 1000));
        int page = Math.max(offset, 0) / pageSize;
        return orderRepository.findPaidValueEvidenceSince(
                since,
                PageRequest.of(page, pageSize)
        );
    }

    @Transactional(readOnly = true)
    public long countPaidValueEvidenceSince(LocalDateTime since) {
        return orderRepository.countPaidValueEvidenceSince(since);
    }

    @Transactional(readOnly = true)
    public Map<String, Object> getCustomerValueFulfillmentEvidence(Order order) {
        if (order == null || !order.isFulfilled()) {
            return Map.of("verified", false, "reason", "order_not_fulfilled");
        }
        if ("item".equalsIgnoreCase(order.getOrderKind()) && order.getItemId() != null) {
            return entitlementService.catalogFulfillmentEvidence(
                    order.getOutTradeNo(),
                    order.getItemId()
            );
        }
        if ("plan".equalsIgnoreCase(order.getOrderKind())
                && order.getPlanId() != null && !order.getPlanId().isBlank()) {
            return entitlementService.planFulfillmentEvidence(
                    order.getOutTradeNo(),
                    order.getPlanId()
            );
        }
        return Map.of("verified", false, "reason", "unsupported_order_kind");
    }

    /** 将非「待支付/已支付/退款中」的订单从列表中隐藏（不删数据）。 */
    @Transactional
    public int dismissNonActiveOrdersForUser(User user) {
        return orderRepository.markDismissedForNonActiveOrders(user);
    }
    
    @Transactional
    public void updateOrderStatus(String outTradeNo, String status, String tradeNo,
                                  String buyerId, LocalDateTime paidAt) {
        Optional<Order> optionalOrder = orderRepository.findByOutTradeNoForUpdate(outTradeNo);
        if (optionalOrder.isPresent()) {
            Order order = optionalOrder.get();
            if ("paid".equals(order.getStatus()) && "paid".equals(status)) {
                return;
            }
            order.setStatus(status);
            if (tradeNo != null) {
                order.setTradeNo(tradeNo);
            }
            if (buyerId != null) {
                order.setBuyerId(buyerId);
            }
            if (paidAt != null) {
                order.setPaidAt(paidAt);
            }
            orderRepository.save(order);
        }
    }
    
    /**
     * 当异步通知未达时，由客户端轮询/回跳后触发：按渠道（微信 Native / 支付宝）查单对账，成功则与 notify 同路径履约。
     */
    public void reconcileWithAlipayIfUnfulfilled(String outTradeNo) {
        Optional<Order> opt = orderRepository.findByOutTradeNo(outTradeNo);
        if (opt.isEmpty()) {
            return;
        }
        Order order = opt.get();
        String localStatus = order.getStatus() == null ? "" : order.getStatus();
        if (!"pending".equals(localStatus)
                && !"closed".equals(localStatus)
                && !("paid".equals(localStatus) && !order.isFulfilled())) {
            return;
        }
        String payType = order.getPayType() == null ? "" : order.getPayType().toLowerCase();
        if (payType.contains("wechat")) {
            Map<String, Object> wx = wechatPayService.queryTransactionByOutTradeNo(outTradeNo);
            if (!Boolean.TRUE.equals(wx.get("ok"))) {
                log.debug("微信对账未成功: outTradeNo={} message={}", outTradeNo, wx.get("message"));
                return;
            }
            String tradeState = String.valueOf(wx.getOrDefault("trade_state", ""));
            if (!"SUCCESS".equals(tradeState)) {
                return;
            }
            String transactionId = wx.get("transaction_id") == null ? null : String.valueOf(wx.get("transaction_id"));
            Object yuanObj = wx.get("payer_total_yuan");
            BigDecimal paidAmount = null;
            if (yuanObj instanceof BigDecimal b) {
                paidAmount = b;
            } else if (yuanObj != null) {
                paidAmount = MoneyUtils.parse(yuanObj);
            }
            try {
                processWechatNotify(outTradeNo, tradeState, transactionId, paidAmount);
            } catch (RuntimeException e) {
                log.warn("微信对账履约失败: outTradeNo={} err={}", outTradeNo, e.getMessage());
            }
            return;
        }
        Map<String, Object> q = alipayService.queryOrder(outTradeNo);
        if (!Boolean.TRUE.equals(q.get("ok"))) {
            log.debug("支付宝对账未成功: outTradeNo={} message={}", outTradeNo, q.get("message"));
            return;
        }
        String ts = String.valueOf(q.getOrDefault("trade_status", ""));
        if (!"TRADE_SUCCESS".equals(ts) && !"TRADE_FINISHED".equals(ts)) {
            return;
        }
        String tradeNo = q.get("trade_no") == null ? null : String.valueOf(q.get("trade_no"));
        String buyerId = q.get("buyer_id") == null ? null : String.valueOf(q.get("buyer_id"));
        Object rawAmt = q.get("total_amount");
        if (rawAmt == null) {
            log.warn("支付宝对账缺少 total_amount: outTradeNo={}", outTradeNo);
            return;
        }
        try {
            processAlipayNotify(outTradeNo, ts, tradeNo, buyerId, MoneyUtils.parse(rawAmt));
        } catch (RuntimeException e) {
            log.warn("支付宝对账履约失败: outTradeNo={} err={}", outTradeNo, e.getMessage());
        }
    }
    
    @Transactional
    public void fulfillOrder(String outTradeNo) {
        fulfillPaidOrderInCurrentTransaction(outTradeNo);
    }

    private void fulfillPaidOrderInCurrentTransaction(String outTradeNo) {
        Optional<Order> optionalOrder = orderRepository.findByOutTradeNoForUpdate(outTradeNo);
        if (optionalOrder.isPresent()) {
            Order order = optionalOrder.get();
            if (!order.isFulfilled() && "paid".equals(order.getStatus())) {
                if ("wallet".equals(order.getOrderKind())) {
                    walletService.credit(order.getUser(), order.getTotalAmount(),
                            "alipay_recharge", "支付宝充值", order.getOutTradeNo(), order.getOutTradeNo(),
                            null, "order:wallet-recharge:" + order.getOutTradeNo());
                } else if ("plan".equals(order.getOrderKind())) {
                    walletService.recordExternalPayment(order);
                    walletService.recordOrderSpend(order);
                    PlanTemplate plan = planTemplateRepository.findById(order.getPlanId())
                            .orElseThrow(() -> new IllegalStateException("套餐不存在"));
                    entitlementService.activatePlan(order.getUser(), plan, order.getOutTradeNo());
                    walletService.grantPlanMembershipTokenAllowance(order);
                } else if ("item".equals(order.getOrderKind())) {
                    walletService.recordExternalPayment(order);
                    walletService.recordOrderSpend(order);
                    entitlementService.createPurchase(order.getUser(), order.getItemId(), order.getTotalAmount());
                    entitlementService.grantCatalogEntitlement(order.getUser(), order.getItemId(), order.getOutTradeNo());
                } else if ("custom_delivery".equals(order.getOrderKind())) {
                    // Service payment: retain real money ledgers without minting
                    // wallet credit, catalog access or plan entitlements.
                    walletService.recordExternalPayment(order);
                    walletService.recordOrderSpend(order);
                } else {
                    throw new IllegalStateException("未知订单类型: " + order.getOrderKind());
                }
                order.setFulfilled(true);
                orderRepository.save(order);
                log.info("订单权益已发放: outTradeNo={}, userId={}, amount={}", 
                        outTradeNo, order.getUser().getId(), order.getTotalAmount());
                try {
                    accountLevelService.applyOrderXp(order);
                } catch (Exception e) {
                    log.warn("订单经验入账失败 (不影响履约): outTradeNo={}, error={}", outTradeNo, e.getMessage());
                }
                webhookDispatcher.publishPaymentPaid(order);
            }
        }
    }
    
    @Transactional
    public void processAlipayNotify(String outTradeNo, String tradeStatus,
                                    String tradeNo, String buyerId, BigDecimal paidAmount) {
        if ("TRADE_SUCCESS".equals(tradeStatus) || "TRADE_FINISHED".equals(tradeStatus)) {
            markPaidThenFulfill(outTradeNo, tradeNo, buyerId, paidAmount);
        }
    }

    @Transactional
    public void processWechatNotify(String outTradeNo, String tradeState,
                                    String transactionId, BigDecimal paidAmount) {
        if ("SUCCESS".equals(tradeState)) {
            markPaidThenFulfill(outTradeNo, transactionId, null, paidAmount);
        }
    }

    private void markPaidThenFulfill(String outTradeNo, String tradeNo, String buyerId, BigDecimal paidAmount) {
        // 先单独提交「已支付」，再履约：避免履约异常拖垮状态落库。
        // 调用方不得持有同一订单的 FOR UPDATE 锁，否则 REQUIRES_NEW 会等待自身外层事务释放锁。
        requiresNewPaidCommitTemplate().executeWithoutResult(status -> {
            Order order = orderRepository.findByOutTradeNoForUpdate(outTradeNo)
                    .orElseThrow(() -> new IllegalArgumentException("订单不存在"));
            if (paidAmount != null && order.getTotalAmount().compareTo(paidAmount) != 0) {
                throw new IllegalArgumentException("支付金额不匹配");
            }
            if ("paid".equals(order.getStatus())) {
                return;
            }
            order.setStatus("paid");
            if (tradeNo != null) {
                order.setTradeNo(tradeNo);
            }
            if (buyerId != null) {
                order.setBuyerId(buyerId);
            }
            order.setPaidAt(LocalDateTime.now());
            orderRepository.save(order);
        });
        requiresNewPaidCommitTemplate().executeWithoutResult(status -> fulfillPaidOrderInCurrentTransaction(outTradeNo));
    }

    @Transactional
    public boolean cancelPendingOrder(User user, String outTradeNo) {
        Optional<Order> optionalOrder = orderRepository.findByOutTradeNoForUpdate(outTradeNo);
        if (optionalOrder.isEmpty()) {
            return false;
        }
        Order order = optionalOrder.get();
        if (!order.getUser().getId().equals(user.getId())) {
            return false;
        }
        if (!"pending".equals(order.getStatus())) {
            return false;
        }
        order.setStatus("closed");
        orderRepository.save(order);
        return true;
    }

    @Transactional
    public void updatePaymentMetadata(String outTradeNo, String payType, String qrCode) {
        orderRepository.findByOutTradeNoForUpdate(outTradeNo).ifPresent(order -> {
            order.setPayType(payType);
            order.setQrCode(qrCode);
            orderRepository.save(order);
        });
    }

    @Transactional
    public int closeExpiredPendingOrders(Duration maxAge) {
        LocalDateTime threshold = LocalDateTime.now().minus(maxAge);
        List<Order> pending = orderRepository.findByStatusAndCreatedAtBefore("pending", threshold);
        pending.forEach(order -> order.setStatus("closed"));
        orderRepository.saveAll(pending);
        return pending.size();
    }

    /**
     * 为历史已支付且已履约的会员单补发「按实付价取整」的随单赠送；已存在同幂等键流水则跳过。仅 status=paid（已退款单为 refunded 等，不补发）。
     */
    @Transactional
    public Map<String, Object> backfillPlanMembershipTokenGrants() {
        List<Order> orders = orderRepository.findByOrderKindAndFulfilledTrueAndStatus("plan", "paid");
        int alreadyHad = 0;
        int newlyCredited = 0;
        int skippedNonPositiveYuan = 0;
        for (Order o : orders) {
            if (MoneyUtils.toIntYuanHalfUp(o.getTotalAmount()) <= 0) {
                skippedNonPositiveYuan++;
                continue;
            }
            String ref = o.getOutTradeNo() + ":membership-tokens";
            String idem = "wallet:credit:plan_membership_tokens:" + ref;
            if (transactionRepository.findByIdempotencyKey(idem).isPresent()) {
                alreadyHad++;
                continue;
            }
            walletService.grantPlanMembershipTokenAllowance(o);
            newlyCredited++;
        }
        Map<String, Object> m = new HashMap<>();
        m.put("ok", true);
        m.put("eligible_plan_orders", orders.size());
        m.put("already_had_token_grant", alreadyHad);
        m.put("newly_credited", newlyCredited);
        m.put("skipped_non_positive_yuan", skippedNonPositiveYuan);
        return m;
    }

    private Long asLong(Object value) {
        if (value == null || String.valueOf(value).isBlank()) {
            return 0L;
        }
        return Long.valueOf(String.valueOf(value));
    }
}
