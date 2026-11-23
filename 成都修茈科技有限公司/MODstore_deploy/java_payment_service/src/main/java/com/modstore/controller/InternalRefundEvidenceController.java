package com.modstore.controller;

import com.modstore.model.Order;
import com.modstore.model.Refund;
import com.modstore.model.Transaction;
import com.modstore.repository.RefundRepository;
import com.modstore.repository.TransactionRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.domain.PageRequest;
import org.springframework.http.HttpStatus;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

import java.math.BigDecimal;
import java.time.Instant;
import java.time.LocalDateTime;
import java.time.ZoneId;
import java.time.temporal.ChronoUnit;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;

/** Read existing CNY wallet credits; never initiate, approve or repeat a refund. */
@RestController
@RequestMapping("/api/internal/payment")
@RequiredArgsConstructor
public class InternalRefundEvidenceController {
    private final InternalPaymentController authentication;
    private final RefundRepository refunds;
    private final TransactionRepository transactions;

    @Value("${modstore.deploy-tier:local}")
    private String deployTier;
    @Value("${alipay.debug:false}")
    private boolean alipayDebug;

    @GetMapping("/refund-evidence")
    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
    public Map<String, Object> evidence(
            @RequestHeader(value = "X-Internal-Api-Key", required = false) String key,
            @RequestParam(name = "window_days", defaultValue = "90") int windowDays,
            @RequestParam(defaultValue = "1000") int limit,
            @RequestParam(defaultValue = "0") long after,
            @RequestParam(name = "through_id", defaultValue = "0") long throughId,
            @RequestParam(name = "as_of", defaultValue = "") String asOf
    ) {
        authentication.requireInternalKey(key);
        Instant now = Instant.now();
        Instant snapshot;
        try {
            snapshot = asOf.isBlank() ? now : Instant.parse(asOf);
        } catch (RuntimeException error) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "refund snapshot invalid");
        }
        if (after < 0 || throughId < 0 || (after > 0 && (throughId == 0 || asOf.isBlank()))
                || snapshot.isAfter(now) || snapshot.isBefore(now.minus(1, ChronoUnit.HOURS))) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "refund cursor invalid");
        }
        int days = Math.min(Math.max(windowDays, 1), 3650);
        int size = Math.min(Math.max(limit, 1), 1000);
        // RefundService and WalletService persist LocalDateTime.now() in the JVM's zone.
        ZoneId zone = ZoneId.systemDefault();
        LocalDateTime at = LocalDateTime.ofInstant(snapshot, zone);
        LocalDateTime since = at.minusDays(days);
        long through = asOf.isBlank() ? refunds.evidenceThroughId(since, at) : throughId;
        long total = refunds.evidenceCount(since, at, through);
        List<Refund> page = refunds.evidencePage(since, at, after, through, PageRequest.of(0, size));
        List<Map<String, Object>> rows = new ArrayList<>();
        for (Refund refund : page) {
            Transaction transaction = refund.getWalletTransactionId() == null ? null
                    : transactions.findById(refund.getWalletTransactionId()).orElse(null);
            Map<String, Object> proof = verifiedProof(refund, transaction, at, zone);
            rows.add(proof == null ? Map.of("refund_id", refund.getId(), "verified", false,
                    "reason", "wallet_refund_evidence_incomplete") : proof);
        }
        long last = page.isEmpty() ? after : page.get(page.size() - 1).getId();
        Map<String, Object> result = new HashMap<>();
        result.put("ok", true);
        result.put("source", "java_postgresql_wallet_refunds_v1");
        result.put("as_of", snapshot.toString());
        result.put("through_id", through);
        result.put("total", total);
        result.put("refunds", rows);
        result.put("next_after", last < through && !page.isEmpty() ? last : null);
        return result;
    }

    private Map<String, Object> verifiedProof(Refund refund, Transaction transaction,
                                              LocalDateTime at, ZoneId zone) {
        Order order = refund.getOrder();
        String tier = deployTier == null ? "" : deployTier.trim().toLowerCase();
        if (alipayDebug || !List.of("production", "prod").contains(tier)
                || order == null || refund.getUser() == null || order.getUser() == null
                || refund.getUser().getId() == null || refund.getUser().getId() <= 0
                || !Objects.equals(refund.getUser().getId(), order.getUser().getId())
                || !"approved".equals(refund.getStatus()) || refund.getReviewedBy() == null
                || !validId(refund.getRefundNo()) || !validId(order.getOutTradeNo())
                || !("refunded".equals(order.getStatus()) || "partial_refunded".equals(order.getStatus()))
                || !Objects.equals(order.getStatus(), order.getRefundStatus())
                || !order.isFulfilled() || order.getPaidAt() == null || order.getRefundedAt() == null
                || refund.getReviewedAt() == null || transaction == null
                || !Objects.equals(transaction.getId(), refund.getWalletTransactionId())
                || transaction.getUser() == null
                || !Objects.equals(transaction.getUser().getId(), refund.getUser().getId())
                || !"wallet_refund".equals(transaction.getTransactionType())
                || !"completed".equals(transaction.getStatus())
                || !Objects.equals(transaction.getOrderNo(), order.getOutTradeNo())
                || !Objects.equals(transaction.getReferenceNo(), order.getOutTradeNo())
                || !Objects.equals(transaction.getRefundNo(), refund.getRefundNo())
                || !Objects.equals(transaction.getIdempotencyKey(), "refund:wallet-credit:" + refund.getRefundNo())
                || transaction.getCreatedAt() == null || transaction.getBalanceBefore() == null
                || transaction.getBalanceAfter() == null || transaction.getAmount() == null
                || refund.getAmount() == null || order.getTotalAmount() == null
                || order.getRefundedAmount() == null) {
            return null;
        }
        BigDecimal amount = refund.getAmount();
        LocalDateTime credited = transaction.getCreatedAt();
        if (amount.signum() <= 0 || amount.compareTo(transaction.getAmount()) != 0
                || transaction.getBalanceAfter().subtract(transaction.getBalanceBefore()).compareTo(amount) != 0
                || order.getRefundedAmount().compareTo(amount) < 0
                || order.getRefundedAmount().compareTo(order.getTotalAmount()) > 0
                || ("refunded".equals(order.getStatus())
                    != (order.getRefundedAmount().compareTo(order.getTotalAmount()) == 0))
                || credited.isBefore(order.getPaidAt()) || refund.getReviewedAt().isBefore(credited)
                || order.getRefundedAt().isBefore(credited) || refund.getReviewedAt().isAfter(at)
                || order.getRefundedAt().isAfter(at)) {
            return null;
        }
        String payType = order.getPayType() == null ? "" : order.getPayType().toLowerCase();
        String provider = payType.contains("wechat") ? "wechat"
                : payType.contains("alipay") || "page".equals(payType) ? "alipay" : "";
        if (provider.isEmpty() || !validId(order.getTradeNo())) {
            return null;
        }
        long cents, totalCents;
        try {
            cents = amount.movePointRight(2).longValueExact();
            totalCents = order.getTotalAmount().movePointRight(2).longValueExact();
        } catch (ArithmeticException invalidMoney) {
            return null;
        }
        Map<String, Object> result = new HashMap<>();
        result.put("verified", true);
        result.put("refund_id", refund.getId());
        result.put("refund_no", refund.getRefundNo());
        result.put("order_no", order.getOutTradeNo());
        result.put("order_subject", order.getSubject() == null ? "" : order.getSubject());
        result.put("order_kind", order.getOrderKind() == null ? "" : order.getOrderKind());
        result.put("user_id", refund.getUser().getId());
        result.put("wallet_transaction_id", transaction.getId());
        result.put("amount_cents", cents);
        // This service's wallet and domestic Alipay/WeChat checkout use yuan, never FX.
        result.put("currency", "CNY");
        result.put("refunded_at", refund.getReviewedAt().atZone(zone).toInstant().toString());
        result.put("credited_at", credited.atZone(zone).toInstant().toString());
        result.put("paid_at", order.getPaidAt().atZone(zone).toInstant().toString());
        result.put("order_total_amount_cents", totalCents);
        result.put("order_status", order.getStatus());
        result.put("payment_provider", provider);
        result.put("provider_trade_no", order.getTradeNo());
        result.put("payment_environment", tier);
        result.put("provider_test_mode", false);
        result.put("verification", "java_wallet_credit_confirmed");
        return result;
    }

    private boolean validId(String value) {
        return value != null && value.matches("[A-Za-z0-9_.:-]{1,128}");
    }
}
