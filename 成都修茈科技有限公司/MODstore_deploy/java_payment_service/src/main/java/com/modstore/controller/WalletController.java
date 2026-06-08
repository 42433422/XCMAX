package com.modstore.controller;

import com.modstore.model.Order;
import com.modstore.model.Refund;
import com.modstore.model.Transaction;
import com.modstore.model.User;
import com.modstore.model.WalletHold;
import com.modstore.service.CurrentUserService;
import com.modstore.service.OrderService;
import com.modstore.service.RefundService;
import com.modstore.service.WalletService;
import com.modstore.util.MoneyUtils;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.web.server.ResponseStatusException;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

@Slf4j
@RestController
@RequestMapping("/api/wallet")
@RequiredArgsConstructor
public class WalletController {
    
    private final WalletService walletService;
    private final CurrentUserService currentUserService;
    private final OrderService orderService;
    private final RefundService refundService;

    @Value("${modstore.admin-recharge-token:}")
    private String adminRechargeToken;

    @Value("${MODSTORE_ADMIN_SELF_CREDIT_CAP:100000}")
    private String adminSelfCreditCapRaw;
    
    @GetMapping
    public Map<String, Object> getWallet() {
        return getBalance();
    }

    @GetMapping("/balance")
    public Map<String, Object> getBalance() {
        try {
            User user = currentUserService.requireCurrentUser();
            return buildBalancePayload(user);
        } catch (Exception e) {
            log.error("获取钱包余额失败", e);
            return Map.of("ok", false, "message", "系统内部错误");
        }
    }

    /** 与 {@link #getBalance()} 相同字段，供资金中心聚合；不吞异常，避免 overview 把错误 JSON 嵌进 wallet。 */
    private Map<String, Object> buildBalancePayload(User user) {
        int refYuan = walletService.getMembershipReferenceLineYuan(user);
        Map<String, Object> m = new HashMap<>();
        m.put("membership_reference_yuan", refYuan);
        walletService.getWallet(user).ifPresentOrElse(
                w -> {
                    m.put("balance", w.getBalance());
                    m.put("updated_at", w.getUpdatedAt());
                },
                () -> {
                    m.put("balance", BigDecimal.ZERO);
                    m.put("updated_at", "");
                }
        );
        return m;
    }

    @PostMapping("/recharge")
    public Map<String, Object> recharge(
            @RequestBody Map<String, Object> body,
            @RequestHeader(value = "X-Modstore-Recharge-Token", required = false) String headerToken
    ) {
        try {
            User user = currentUserService.requireCurrentUser();
            if (!user.isAdmin()) {
                throw new ResponseStatusException(HttpStatus.FORBIDDEN, "仅管理员可使用 Token 直充接口，且只能为当前登录账号加款");
            }
            String configuredToken = adminRechargeToken == null ? "" : adminRechargeToken.trim();
            if (configuredToken.isEmpty()) {
                throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "未配置 MODSTORE_ADMIN_RECHARGE_TOKEN，无法直充");
            }
            String bodyToken = String.valueOf(body.getOrDefault("recharge_token", "")).trim();
            String clientToken = headerToken != null && !headerToken.trim().isEmpty() ? headerToken.trim() : bodyToken;
            if (!configuredToken.equals(clientToken)) {
                throw new ResponseStatusException(HttpStatus.FORBIDDEN, "无效的充值授权");
            }
            BigDecimal amount = MoneyUtils.parse(body.get("amount"));
            if (amount.compareTo(BigDecimal.ZERO) <= 0) {
                return Map.of("ok", false, "message", "充值金额必须大于 0");
            }
            String description = String.valueOf(body.getOrDefault("description", "后台钱包充值"));
            walletService.addBalance(user, amount, "manual_recharge", description);
            return Map.of("ok", true, "balance", walletService.getBalance(user));
        } catch (ResponseStatusException e) {
            throw e;
        } catch (Exception e) {
            log.error("钱包充值失败", e);
            return Map.of("ok", false, "message", "系统内部错误");
        }
    }

    /**
     * 管理员为本人钱包加款（仅 JWT + is_admin），不依赖共享直充 Token；不能指定他人账号。
     */
    @PostMapping("/admin-self-credit")
    public Map<String, Object> adminSelfCredit(@RequestBody Map<String, Object> body) {
        try {
            User user = currentUserService.requireCurrentUser();
            if (!user.isAdmin()) {
                throw new ResponseStatusException(HttpStatus.FORBIDDEN, "仅管理员可为本人钱包加款");
            }
            BigDecimal cap;
            try {
                cap = new BigDecimal(adminSelfCreditCapRaw == null || adminSelfCreditCapRaw.isBlank()
                        ? "100000"
                        : adminSelfCreditCapRaw.trim());
                if (cap.compareTo(BigDecimal.ONE) < 0) {
                    cap = new BigDecimal("100000");
                }
            } catch (NumberFormatException e) {
                cap = new BigDecimal("100000");
            }
            BigDecimal amount = MoneyUtils.parse(body.get("amount"));
            if (amount.compareTo(BigDecimal.ZERO) <= 0) {
                return Map.of("ok", false, "message", "金额必须大于 0");
            }
            if (amount.compareTo(cap) > 0) {
                throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "单次加款不能超过 " + cap.stripTrailingZeros().toPlainString() + " 元");
            }
            String description = String.valueOf(body.getOrDefault("description", "管理员本人加款")).trim();
            if (description.isEmpty()) {
                description = "管理员本人加款";
            }
            walletService.addBalance(user, amount, "admin_self_credit", description);
            return Map.of("ok", true, "balance", walletService.getBalance(user));
        } catch (ResponseStatusException e) {
            throw e;
        } catch (Exception e) {
            log.error("管理员本人加款失败", e);
            return Map.of("ok", false, "message", "系统内部错误");
        }
    }

    @PostMapping("/ai/preauthorize")
    public Map<String, Object> preauthorizeAiUsage(@RequestBody Map<String, Object> body) {
        try {
            User user = currentUserService.requireCurrentUser();
            WalletHold hold = walletService.preauthorizeAiUsage(
                    user,
                    MoneyUtils.parse(body.get("amount")),
                    String.valueOf(body.getOrDefault("provider", "")),
                    String.valueOf(body.getOrDefault("model", "")),
                    String.valueOf(body.getOrDefault("request_id", "")),
                    String.valueOf(body.getOrDefault("idempotency_key", ""))
            );
            return Map.of("ok", true, "hold", holdToMap(hold), "balance", walletService.getBalance(user));
        } catch (Exception e) {
            log.warn("AI 用量预授权失败: {}", e.getMessage());
            return Map.of("ok", false, "message", e.getMessage());
        }
    }

    @PostMapping("/ai/settle")
    public Map<String, Object> settleAiUsage(@RequestBody Map<String, Object> body) {
        try {
            User user = currentUserService.requireCurrentUser();
            WalletHold hold = walletService.settleAiUsage(
                    user,
                    String.valueOf(body.getOrDefault("hold_no", "")),
                    MoneyUtils.parse(body.get("actual_amount")),
                    String.valueOf(body.getOrDefault("idempotency_key", ""))
            );
            return Map.of("ok", true, "hold", holdToMap(hold), "balance", walletService.getBalance(user));
        } catch (Exception e) {
            log.warn("AI 用量结算失败: {}", e.getMessage());
            return Map.of("ok", false, "message", e.getMessage());
        }
    }

    @PostMapping("/ai/release")
    public Map<String, Object> releaseAiUsage(@RequestBody Map<String, Object> body) {
        try {
            User user = currentUserService.requireCurrentUser();
            WalletHold hold = walletService.releaseAiUsage(
                    user,
                    String.valueOf(body.getOrDefault("hold_no", "")),
                    String.valueOf(body.getOrDefault("reason", "")),
                    String.valueOf(body.getOrDefault("idempotency_key", ""))
            );
            return Map.of("ok", true, "hold", holdToMap(hold), "balance", walletService.getBalance(user));
        } catch (Exception e) {
            log.warn("AI 用量预授权释放失败: {}", e.getMessage());
            return Map.of("ok", false, "message", e.getMessage());
        }
    }

    @GetMapping("/transactions")
    public Map<String, Object> getTransactions(
            @RequestParam(defaultValue = "50") int limit,
            @RequestParam(defaultValue = "0") int offset
    ) {
        try {
            User user = currentUserService.requireCurrentUser();
            List<Transaction> transactions = walletService.getTransactions(user, limit, offset);
            long total = walletService.countTransactions(user);
            
            List<Map<String, Object>> transactionList = new ArrayList<>();
            for (Transaction transaction : transactions) {
                Map<String, Object> transactionMap = new HashMap<>();
                transactionMap.put("id", transaction.getId());
                transactionMap.put("amount", transaction.getAmount());
                transactionMap.put("txn_type", transaction.getTransactionType());
                transactionMap.put("type", transaction.getTransactionType());
                transactionMap.put("status", transaction.getStatus());
                transactionMap.put("description", transaction.getDescription());
                transactionMap.put("reference_no", transaction.getReferenceNo());
                transactionMap.put("order_no", transaction.getOrderNo());
                transactionMap.put("refund_no", transaction.getRefundNo());
                transactionMap.put("balance_before", transaction.getBalanceBefore());
                transactionMap.put("balance_after", transaction.getBalanceAfter());
                transactionMap.put("created_at", transaction.getCreatedAt());
                transactionList.add(transactionMap);
            }
            
            return Map.of("transactions", transactionList, "total", total);
        } catch (Exception e) {
            log.error("获取交易记录失败", e);
            return Map.of("ok", false, "message", "系统内部错误");
        }
    }

    @GetMapping("/overview")
    public Map<String, Object> overview(
            @RequestParam(defaultValue = "20") int limit,
            @RequestParam(defaultValue = "0") int offset
    ) {
        try {
            User user = currentUserService.requireCurrentUser();
            Map<String, Object> wallet = buildBalancePayload(user);
            List<Map<String, Object>> transactions = walletService.getTransactions(user, limit, offset).stream()
                    .map(this::transactionToMap)
                    .toList();
            List<Map<String, Object>> orders = orderService.findByUser(user, null, limit, offset).stream()
                    .map(this::orderToMap)
                    .toList();
            List<Map<String, Object>> refunds = refundService.findByUser(user, limit, offset).stream()
                    .map(this::refundToMap)
                    .toList();
            return Map.of(
                    "wallet", wallet,
                    "transactions", transactions,
                    "transaction_total", walletService.countTransactions(user),
                    "orders", orders,
                    "order_total", orderService.countByUser(user, null),
                    "refunds", refunds,
                    "refund_total", refundService.countByUser(user)
            );
        } catch (Exception e) {
            log.error("获取钱包资金中心失败", e);
            return Map.of("ok", false, "message", "系统内部错误");
        }
    }

    private Map<String, Object> transactionToMap(Transaction transaction) {
        Map<String, Object> transactionMap = new HashMap<>();
        transactionMap.put("id", transaction.getId());
        transactionMap.put("amount", transaction.getAmount());
        transactionMap.put("txn_type", transaction.getTransactionType());
        transactionMap.put("type", transaction.getTransactionType());
        transactionMap.put("status", transaction.getStatus());
        transactionMap.put("description", transaction.getDescription());
        transactionMap.put("reference_no", transaction.getReferenceNo());
        transactionMap.put("order_no", transaction.getOrderNo());
        transactionMap.put("refund_no", transaction.getRefundNo());
        transactionMap.put("balance_before", transaction.getBalanceBefore());
        transactionMap.put("balance_after", transaction.getBalanceAfter());
        transactionMap.put("created_at", transaction.getCreatedAt());
        return transactionMap;
    }

    private Map<String, Object> orderToMap(Order order) {
        Map<String, Object> row = new HashMap<>();
        row.put("out_trade_no", order.getOutTradeNo());
        row.put("status", order.getStatus());
        row.put("subject", order.getSubject());
        row.put("total_amount", order.getTotalAmount());
        row.put("order_kind", order.getOrderKind());
        row.put("refund_status", order.getRefundStatus());
        row.put("refunded_amount", order.getRefundedAmount());
        row.put("created_at", order.getCreatedAt());
        row.put("paid_at", order.getPaidAt());
        return row;
    }

    private Map<String, Object> refundToMap(Refund refund) {
        Map<String, Object> row = new HashMap<>();
        row.put("id", refund.getId());
        row.put("refund_no", refund.getRefundNo());
        row.put("order_no", refund.getOrder().getOutTradeNo());
        row.put("amount", refund.getAmount());
        row.put("reason", refund.getReason());
        row.put("status", refund.getStatus());
        row.put("wallet_transaction_id", refund.getWalletTransactionId());
        row.put("created_at", refund.getCreatedAt());
        row.put("reviewed_at", refund.getReviewedAt());
        return row;
    }

    private Map<String, Object> holdToMap(WalletHold hold) {
        Map<String, Object> row = new HashMap<>();
        row.put("id", hold.getId());
        row.put("hold_no", hold.getHoldNo());
        row.put("amount", hold.getAmount());
        row.put("settled_amount", hold.getSettledAmount());
        row.put("status", hold.getStatus());
        row.put("provider", hold.getProvider());
        row.put("model", hold.getModel());
        row.put("request_id", hold.getRequestId());
        row.put("preauth_transaction_id", hold.getPreauthTransactionId());
        row.put("settlement_transaction_id", hold.getSettlementTransactionId());
        row.put("created_at", hold.getCreatedAt());
        row.put("expires_at", hold.getExpiresAt());
        row.put("settled_at", hold.getSettledAt());
        row.put("released_at", hold.getReleasedAt());
        return row;
    }
}
