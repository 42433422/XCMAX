package com.modstore.service;

import com.modstore.model.Order;
import com.modstore.model.Refund;
import com.modstore.model.Transaction;
import com.modstore.model.User;
import com.modstore.repository.OrderRepository;
import com.modstore.repository.RefundRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.data.domain.PageRequest;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Optional;

@Slf4j
@Service
@RequiredArgsConstructor
public class RefundService {

    private static final List<String> OPEN_REFUND_STATUSES = List.of("pending", "approved");

    private final RefundRepository refundRepository;
    private final OrderRepository orderRepository;
    private final WalletService walletService;
    private final EntitlementService entitlementService;
    private final AccountLevelService accountLevelService;

    @Transactional
    public Refund apply(User user, String orderNo, String reason) {
        String normalizedOrderNo = requireText(orderNo, "订单号不能为空");
        String normalizedReason = requireText(reason, "退款原因不能为空");
        if (normalizedReason.length() < 5 || normalizedReason.length() > 1000) {
            throw new IllegalArgumentException("退款原因需为 5-1000 字");
        }

        Order order = orderRepository.findByOutTradeNoForUpdate(normalizedOrderNo)
                .orElseThrow(() -> new IllegalArgumentException("订单不存在"));
        if (!order.getUser().getId().equals(user.getId())) {
            throw new IllegalArgumentException("无权申请该订单退款");
        }
        if (!order.isFulfilled() || !"paid".equals(order.getStatus())) {
            throw new IllegalArgumentException("仅已支付并完成履约的订单可申请退款");
        }
        if ("wallet".equals(order.getOrderKind())) {
            throw new IllegalArgumentException("钱包充值订单已入余额，不能再退款到钱包");
        }
        BigDecimal refundedAmount = order.getRefundedAmount() == null ? BigDecimal.ZERO : order.getRefundedAmount();
        BigDecimal refundableAmount = order.getTotalAmount().subtract(refundedAmount);
        if (refundableAmount.compareTo(BigDecimal.ZERO) <= 0) {
            throw new IllegalArgumentException("该订单已退款");
        }
        Optional<Refund> openRefund = refundRepository.findFirstByOrderAndStatusIn(order, OPEN_REFUND_STATUSES);
        if (openRefund.isPresent()) {
            return openRefund.get();
        }

        Refund refund = new Refund();
        refund.setRefundNo("RF" + System.currentTimeMillis() + user.getId());
        refund.setOrder(order);
        refund.setUser(user);
        refund.setAmount(refundableAmount);
        refund.setReason(normalizedReason);
        refund.setStatus("pending");
        Refund saved = refundRepository.save(refund);

        order.setStatus("refunding");
        order.setRefundStatus("pending");
        orderRepository.save(order);
        return saved;
    }

    @Transactional
    public Refund review(User admin, Long refundId, String action, String adminNote) {
        if (!admin.isAdmin()) {
            throw new IllegalArgumentException("需要管理员权限");
        }
        Refund refund = refundRepository.findByIdForUpdate(refundId)
                .orElseThrow(() -> new IllegalArgumentException("退款申请不存在"));
        if (!"pending".equals(refund.getStatus())) {
            return refund;
        }

        String normalizedAction = requireText(action, "审核动作不能为空").toLowerCase();
        Order order = orderRepository.findByOutTradeNoForUpdate(refund.getOrder().getOutTradeNo())
                .orElseThrow(() -> new IllegalArgumentException("订单不存在"));
        if ("approve".equals(normalizedAction) || "approved".equals(normalizedAction)) {
            Transaction walletTransaction = walletService.refundToWallet(order, refund);
            entitlementService.revokeOrderEntitlements(refund.getUser(), order.getOutTradeNo());
            if ("plan".equals(order.getOrderKind())) {
                walletService.revokePlanMembershipTokenAllowance(order);
            }
            try {
                accountLevelService.revokeOrderXp(refund.getUser().getId(), order.getOutTradeNo());
            } catch (Exception e) {
                log.warn("退款扣回经验失败: orderNo={}, error={}", order.getOutTradeNo(), e.getMessage());
            }

            BigDecimal alreadyRefunded = order.getRefundedAmount() == null ? BigDecimal.ZERO : order.getRefundedAmount();
            BigDecimal totalRefunded = alreadyRefunded.add(refund.getAmount());
            order.setRefundedAmount(totalRefunded);
            order.setRefundStatus(totalRefunded.compareTo(order.getTotalAmount()) >= 0 ? "refunded" : "partial_refunded");
            order.setStatus(totalRefunded.compareTo(order.getTotalAmount()) >= 0 ? "refunded" : "partial_refunded");
            order.setRefundedAt(LocalDateTime.now());
            orderRepository.save(order);

            refund.setStatus("approved");
            refund.setWalletTransactionId(walletTransaction.getId());
            log.info("退款审核通过并退回钱包: refundNo={}, orderNo={}, amount={}",
                    refund.getRefundNo(), order.getOutTradeNo(), refund.getAmount());
        } else if ("reject".equals(normalizedAction) || "rejected".equals(normalizedAction)) {
            refund.setStatus("rejected");
            order.setStatus("paid");
            order.setRefundStatus("rejected");
            orderRepository.save(order);
        } else {
            throw new IllegalArgumentException("无效的审核动作");
        }

        refund.setAdminNote(adminNote == null ? "" : adminNote.trim());
        refund.setReviewedBy(admin);
        refund.setReviewedAt(LocalDateTime.now());
        return refundRepository.save(refund);
    }

    @Transactional(readOnly = true)
    public List<Refund> findByUser(User user, int limit, int offset) {
        int pageSize = Math.max(1, Math.min(limit, 200));
        int page = Math.max(offset, 0) / pageSize;
        return refundRepository.findByUserOrderByCreatedAtDesc(user, PageRequest.of(page, pageSize));
    }

    @Transactional(readOnly = true)
    public long countByUser(User user) {
        return refundRepository.countByUser(user);
    }

    @Transactional(readOnly = true)
    public List<Refund> findPending(int limit, int offset) {
        int pageSize = Math.max(1, Math.min(limit, 200));
        int page = Math.max(offset, 0) / pageSize;
        return refundRepository.findByStatusOrderByCreatedAtAsc("pending", PageRequest.of(page, pageSize));
    }

    private String requireText(String value, String message) {
        String normalized = value == null ? "" : value.trim();
        if (normalized.isBlank()) {
            throw new IllegalArgumentException(message);
        }
        return normalized;
    }
}
