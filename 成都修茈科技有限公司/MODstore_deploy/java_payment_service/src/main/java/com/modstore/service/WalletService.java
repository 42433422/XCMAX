package com.modstore.service;

import com.modstore.model.Transaction;
import com.modstore.model.User;
import com.modstore.model.Wallet;
import com.modstore.model.WalletHold;
import com.modstore.model.Order;
import com.modstore.model.Refund;
import com.modstore.repository.TransactionRepository;
import com.modstore.repository.UserPlanRepository;
import com.modstore.repository.WalletHoldRepository;
import com.modstore.repository.WalletRepository;
import com.modstore.util.MoneyUtils;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.data.domain.PageRequest;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Optional;
import java.util.UUID;

@Slf4j
@Service
@RequiredArgsConstructor
public class WalletService {
    
    private final WalletRepository walletRepository;
    private final TransactionRepository transactionRepository;
    private final WalletHoldRepository walletHoldRepository;
    private final UserPlanRepository userPlanRepository;
    private final AccountLevelService accountLevelService;
    
    @Transactional
    public Wallet getOrCreateWallet(User user) {
        return walletRepository.findByUser(user)
                .orElseGet(() -> {
                    Wallet wallet = new Wallet();
                    wallet.setUser(user);
                    wallet.setBalance(BigDecimal.ZERO);
                    return walletRepository.save(wallet);
                });
    }
    
    @Transactional
    public BigDecimal getBalance(User user) {
        Wallet wallet = getOrCreateWallet(user);
        return wallet.getBalance();
    }

    @Transactional(readOnly = true)
    public Optional<Wallet> getWallet(User user) {
        return walletRepository.findByUser(user);
    }

    /**
     * 钱包页「会员额度参考线」（元，整数）：
     * 优先为「随单 membership 赠送 + 退款扣回」的累计净值（升级多次购买会自然累加）；
     * 若无此类流水、当前有有效套餐，则取当前套餐价四舍五入的整数元（单独购/未落流水时的展示兜底）。
     */
    @Transactional(readOnly = true)
    public int getMembershipReferenceLineYuan(User user) {
        BigDecimal net = transactionRepository.sumMembershipReferenceNet(user);
        if (net == null) {
            net = BigDecimal.ZERO;
        }
        int n = net.setScale(0, RoundingMode.HALF_UP).intValue();
        if (n < 0) {
            n = 0;
        }
        if (n == 0) {
            n = userPlanRepository.findFirstByUserAndActiveTrueOrderByStartedAtDesc(user)
                    .map(up -> MoneyUtils.toIntYuanHalfUp(up.getPlan().getPrice()))
                    .orElse(0);
        }
        return n;
    }
    
    @Transactional
    public void addBalance(User user, BigDecimal amount, String transactionType, String description) {
        addBalance(user, amount, transactionType, description, null);
    }

    @Transactional
    public void addBalance(User user, BigDecimal amount, String transactionType, String description, String referenceNo) {
        credit(user, amount, transactionType, description, referenceNo, referenceNo, null,
                referenceNo == null ? null : "wallet:credit:" + transactionType + ":" + referenceNo);
    }
    
    @Transactional
    public void deductBalance(User user, BigDecimal amount, String transactionType, String description) {
        debit(user, amount, transactionType, description, null, null, null, null);
    }

    /**
     * 会员套餐：除套餐权益外，按实付价（元）四舍五入的整数，增加钱包可用余额，用于平台 LLM 等按量消费。
     * 与 {@link #revokePlanMembershipTokenAllowance(Order)} 对称，退款时扣回。
     */
    @Transactional
    public void grantPlanMembershipTokenAllowance(Order order) {
        if (order == null || !"plan".equals(order.getOrderKind())) {
            return;
        }
        int grantYuan = MoneyUtils.toIntYuanHalfUp(order.getTotalAmount());
        if (grantYuan <= 0) {
            return;
        }
        addBalance(
                order.getUser(),
                BigDecimal.valueOf(grantYuan),
                "plan_membership_tokens",
                "会员随单：按实付价取整的 LLM 可用余额(元)",
                order.getOutTradeNo() + ":membership-tokens"
        );
    }

    /**
     * 会员订单退款时扣回与 {@link #grantPlanMembershipTokenAllowance} 等额的入金；若已部分消费，按当前可用余额取较小值扣回。
     */
    @Transactional
    public void revokePlanMembershipTokenAllowance(Order order) {
        if (order == null || !"plan".equals(order.getOrderKind())) {
            return;
        }
        int grantYuan = MoneyUtils.toIntYuanHalfUp(order.getTotalAmount());
        if (grantYuan <= 0) {
            return;
        }
        BigDecimal toTake = BigDecimal.valueOf(grantYuan);
        User user = order.getUser();
        getOrCreateWallet(user);
        BigDecimal available = getBalance(user);
        if (available.compareTo(BigDecimal.ZERO) <= 0) {
            log.warn("扣回会员赠送余额：无可用余额, order={}", order.getOutTradeNo());
            return;
        }
        BigDecimal actual = toTake.min(available);
        debit(
                user,
                actual,
                "plan_membership_tokens_revoke",
                "会员退款：扣回按实付价取整的随单赠送(元)",
                order.getOutTradeNo() + ":mt-revoke",
                order.getOutTradeNo(),
                null,
                "plan-tok-revoke:" + order.getOutTradeNo()
        );
    }

    @Transactional
    public Transaction recordExternalPayment(Order order) {
        return credit(
                order.getUser(),
                order.getTotalAmount(),
                "alipay_payment",
                "支付宝支付入钱包: " + order.getSubject(),
                order.getOutTradeNo(),
                order.getOutTradeNo(),
                null,
                "order:alipay-credit:" + order.getOutTradeNo()
        );
    }

    @Transactional
    public Transaction recordOrderSpend(Order order) {
        return debit(
                order.getUser(),
                order.getTotalAmount(),
                orderSpendType(order.getOrderKind()),
                "订单消费: " + order.getSubject(),
                order.getOutTradeNo(),
                order.getOutTradeNo(),
                null,
                "order:wallet-debit:" + order.getOutTradeNo()
        );
    }

    @Transactional
    public Transaction refundToWallet(Order order, Refund refund) {
        return credit(
                refund.getUser(),
                refund.getAmount(),
                "wallet_refund",
                "退款入钱包: " + order.getSubject(),
                order.getOutTradeNo(),
                order.getOutTradeNo(),
                refund.getRefundNo(),
                "refund:wallet-credit:" + refund.getRefundNo()
        );
    }

    @Transactional
    public WalletHold preauthorizeAiUsage(User user, BigDecimal amount, String provider, String model,
                                          String requestId, String idempotencyKey) {
        validatePositiveAmount(amount);
        String safeIdempotencyKey = requireIdempotencyKey(idempotencyKey);
        Optional<WalletHold> existing = walletHoldRepository.findByIdempotencyKey(safeIdempotencyKey);
        if (existing.isPresent()) {
            return existing.get();
        }

        String holdNo = "AIH" + UUID.randomUUID().toString().replace("-", "").substring(0, 16);
        Transaction transaction = debit(
                user,
                amount,
                "ai_preauth",
                "AI 调用预授权: " + trimForDescription(provider) + "/" + trimForDescription(model),
                requestId,
                holdNo,
                null,
                "ai:preauth:" + safeIdempotencyKey
        );

        WalletHold hold = new WalletHold();
        hold.setUser(user);
        hold.setHoldNo(holdNo);
        hold.setAmount(amount);
        hold.setSettledAmount(BigDecimal.ZERO);
        hold.setStatus("held");
        hold.setProvider(trim(provider, 64));
        hold.setModel(trim(model, 128));
        hold.setRequestId(trim(requestId, 128));
        hold.setIdempotencyKey(safeIdempotencyKey);
        hold.setPreauthTransactionId(transaction.getId());
        hold.setExpiresAt(LocalDateTime.now().plusMinutes(10));
        return walletHoldRepository.save(hold);
    }

    @Transactional
    public WalletHold settleAiUsage(User user, String holdNo, BigDecimal actualAmount, String idempotencyKey) {
        if (actualAmount == null || actualAmount.compareTo(BigDecimal.ZERO) < 0) {
            throw new IllegalArgumentException("结算金额不能小于 0");
        }
        WalletHold hold = requireOwnedHold(user, holdNo);
        if ("settled".equals(hold.getStatus())) {
            return hold;
        }
        if ("released".equals(hold.getStatus())) {
            throw new IllegalStateException("预授权已释放，不能结算");
        }

        BigDecimal reserved = hold.getAmount();
        BigDecimal delta = actualAmount.subtract(reserved);
        Transaction settlement = null;
        String safeIdempotencyKey = requireIdempotencyKey(idempotencyKey);
        if (delta.compareTo(BigDecimal.ZERO) > 0) {
            settlement = debit(
                    user,
                    delta,
                    "ai_settle_extra",
                    "AI 调用补扣: " + hold.getProvider() + "/" + hold.getModel(),
                    hold.getRequestId(),
                    hold.getHoldNo(),
                    null,
                    "ai:settle-extra:" + safeIdempotencyKey
            );
        } else if (delta.compareTo(BigDecimal.ZERO) < 0) {
            settlement = credit(
                    user,
                    delta.abs(),
                    "ai_release",
                    "AI 调用释放余额: " + hold.getProvider() + "/" + hold.getModel(),
                    hold.getRequestId(),
                    hold.getHoldNo(),
                    null,
                    "ai:settle-release:" + safeIdempotencyKey
            );
        }
        hold.setSettledAmount(actualAmount);
        hold.setStatus("settled");
        hold.setSettlementTransactionId(settlement == null ? null : settlement.getId());
        hold.setSettledAt(LocalDateTime.now());
        WalletHold saved = walletHoldRepository.save(hold);
        if (actualAmount.compareTo(BigDecimal.ZERO) > 0) {
            try {
                String desc = "大模型按量扣费经验 ("
                        + trimForDescription(hold.getProvider()) + "/" + trimForDescription(hold.getModel()) + ")";
                accountLevelService.applyLlmConsumptionXp(user.getId(), safeIdempotencyKey, actualAmount, desc);
            } catch (Exception e) {
                log.warn("LLM 经验入账失败 (不影响结算): userId={} holdNo={} err={}",
                        user.getId(), holdNo, e.getMessage());
            }
        }
        return saved;
    }

    @Transactional
    public WalletHold releaseAiUsage(User user, String holdNo, String reason, String idempotencyKey) {
        WalletHold hold = requireOwnedHold(user, holdNo);
        if ("released".equals(hold.getStatus()) || "settled".equals(hold.getStatus())) {
            return hold;
        }
        String safeIdempotencyKey = requireIdempotencyKey(idempotencyKey);
        Transaction release = credit(
                user,
                hold.getAmount(),
                "ai_release",
                "AI 调用预授权释放: " + trimForDescription(reason),
                hold.getRequestId(),
                hold.getHoldNo(),
                null,
                "ai:release:" + safeIdempotencyKey
        );
        hold.setSettledAmount(BigDecimal.ZERO);
        hold.setStatus("released");
        hold.setSettlementTransactionId(release.getId());
        hold.setReleasedAt(LocalDateTime.now());
        return walletHoldRepository.save(hold);
    }

    @Transactional
    public Transaction credit(User user, BigDecimal amount, String transactionType, String description,
                              String referenceNo, String orderNo, String refundNo, String idempotencyKey) {
        validatePositiveAmount(amount);
        return changeBalance(user, amount, transactionType, description, referenceNo, orderNo, refundNo, idempotencyKey);
    }

    @Transactional
    public Transaction debit(User user, BigDecimal amount, String transactionType, String description,
                             String referenceNo, String orderNo, String refundNo, String idempotencyKey) {
        validatePositiveAmount(amount);
        return changeBalance(user, amount.negate(), transactionType, description, referenceNo, orderNo, refundNo, idempotencyKey);
    }
    
    @Transactional(readOnly = true)
    public List<Transaction> getTransactions(User user, int limit, int offset) {
        int pageSize = Math.max(1, Math.min(limit, 200));
        int page = Math.max(offset, 0) / pageSize;
        return transactionRepository.findByUserOrderByCreatedAtDesc(user, PageRequest.of(page, pageSize));
    }
    
    @Transactional(readOnly = true)
    public long countTransactions(User user) {
        return transactionRepository.countByUser(user);
    }

    @Transactional(readOnly = true)
    public List<Transaction> getTransactionsForOrder(User user, String orderNo) {
        return transactionRepository.findByUserAndOrderNoOrderByCreatedAtDesc(user, orderNo);
    }

    private Transaction changeBalance(User user, BigDecimal signedAmount, String transactionType, String description,
                                      String referenceNo, String orderNo, String refundNo, String idempotencyKey) {
        if (idempotencyKey != null && !idempotencyKey.isBlank()) {
            Optional<Transaction> existing = transactionRepository.findByIdempotencyKey(idempotencyKey);
            if (existing.isPresent()) {
                return existing.get();
            }
        }

        Wallet wallet = walletRepository.findByUserIdForUpdate(user.getId()).orElseGet(() -> getOrCreateWallet(user));
        BigDecimal before = wallet.getBalance() == null ? BigDecimal.ZERO : wallet.getBalance();
        BigDecimal after = before.add(signedAmount);
        if (after.compareTo(BigDecimal.ZERO) < 0) {
            throw new IllegalArgumentException("余额不足");
        }
        wallet.setBalance(after);
        walletRepository.save(wallet);

        Transaction transaction = recordTransaction(user, signedAmount, transactionType, description,
                referenceNo, orderNo, refundNo, idempotencyKey, before, after);

        log.info("钱包余额变更: userId={}, amount={}, before={}, after={}, type={}, ref={}",
                user.getId(), signedAmount, before, after, transactionType, referenceNo);
        return transaction;
    }

    private Transaction recordTransaction(User user, BigDecimal amount, String transactionType, String description,
                                          String referenceNo, String orderNo, String refundNo, String idempotencyKey,
                                          BigDecimal balanceBefore, BigDecimal balanceAfter) {
        Transaction transaction = new Transaction();
        transaction.setUser(user);
        transaction.setAmount(amount);
        transaction.setBalanceBefore(balanceBefore);
        transaction.setBalanceAfter(balanceAfter);
        transaction.setTransactionType(transactionType);
        transaction.setStatus("completed");
        transaction.setDescription(description);
        transaction.setReferenceNo(referenceNo);
        transaction.setOrderNo(orderNo);
        transaction.setRefundNo(refundNo);
        transaction.setIdempotencyKey(idempotencyKey);
        return transactionRepository.save(transaction);
    }

    private void validatePositiveAmount(BigDecimal amount) {
        if (amount == null || amount.compareTo(BigDecimal.ZERO) <= 0) {
            throw new IllegalArgumentException("金额必须大于 0");
        }
    }

    private WalletHold requireOwnedHold(User user, String holdNo) {
        String safeHoldNo = (holdNo == null ? "" : holdNo.trim());
        if (safeHoldNo.isEmpty()) {
            throw new IllegalArgumentException("预授权单号不能为空");
        }
        WalletHold hold = walletHoldRepository.findByHoldNo(safeHoldNo)
                .orElseThrow(() -> new IllegalArgumentException("预授权不存在"));
        if (!hold.getUser().getId().equals(user.getId())) {
            throw new IllegalStateException("无权操作该预授权");
        }
        return hold;
    }

    private String requireIdempotencyKey(String raw) {
        String key = raw == null ? "" : raw.trim();
        if (key.isEmpty()) {
            throw new IllegalArgumentException("idempotency_key 不能为空");
        }
        return trim(key, 128);
    }

    private String trimForDescription(String value) {
        return trim(value == null || value.isBlank() ? "-" : value, 96);
    }

    private String trim(String value, int maxLength) {
        String v = value == null ? "" : value.trim();
        return v.length() <= maxLength ? v : v.substring(0, maxLength);
    }

    private String orderSpendType(String orderKind) {
        if ("plan".equals(orderKind)) {
            return "plan_purchase";
        }
        if ("item".equals(orderKind)) {
            return "item_purchase";
        }
        return "order_purchase";
    }
}
