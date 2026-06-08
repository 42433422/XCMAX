package com.modstore.controller;

import com.modstore.model.Refund;
import com.modstore.model.User;
import com.modstore.service.CurrentUserService;
import com.modstore.service.RefundService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.*;

import java.util.HashMap;
import java.util.List;
import java.util.Map;

@Slf4j
@RestController
@RequestMapping("/api/refunds")
@RequiredArgsConstructor
public class RefundController {

    private final RefundService refundService;
    private final CurrentUserService currentUserService;

    @PostMapping("/apply")
    public Map<String, Object> apply(@RequestBody Map<String, Object> body) {
        try {
            User user = currentUserService.requireCurrentUser();
            Refund refund = refundService.apply(
                    user,
                    String.valueOf(body.getOrDefault("order_no", "")),
                    String.valueOf(body.getOrDefault("reason", ""))
            );
            return Map.of("ok", true, "refund", refundToMap(refund));
        } catch (Exception e) {
            log.warn("退款申请失败: {}", e.getMessage());
            return Map.of("ok", false, "message", e.getMessage());
        }
    }

    @GetMapping("/my")
    public Map<String, Object> myRefunds(
            @RequestParam(defaultValue = "50") int limit,
            @RequestParam(defaultValue = "0") int offset
    ) {
        User user = currentUserService.requireCurrentUser();
        List<Map<String, Object>> rows = refundService.findByUser(user, limit, offset).stream()
                .map(this::refundToMap)
                .toList();
        return Map.of("refunds", rows, "total", refundService.countByUser(user));
    }

    @GetMapping("/admin/pending")
    public Map<String, Object> pending(
            @RequestParam(defaultValue = "50") int limit,
            @RequestParam(defaultValue = "0") int offset
    ) {
        User user = currentUserService.requireCurrentUser();
        if (!user.isAdmin()) {
            return Map.of("ok", false, "message", "需要管理员权限");
        }
        List<Map<String, Object>> rows = refundService.findPending(limit, offset).stream()
                .map(this::refundToMap)
                .toList();
        return Map.of("refunds", rows, "total", rows.size());
    }

    @PostMapping("/admin/{refundId}/review")
    public Map<String, Object> review(@PathVariable Long refundId, @RequestBody Map<String, Object> body) {
        try {
            User user = currentUserService.requireCurrentUser();
            Refund refund = refundService.review(
                    user,
                    refundId,
                    String.valueOf(body.getOrDefault("action", "")),
                    String.valueOf(body.getOrDefault("admin_note", ""))
            );
            return Map.of("ok", true, "refund", refundToMap(refund));
        } catch (Exception e) {
            log.warn("退款审核失败: {}", e.getMessage());
            return Map.of("ok", false, "message", e.getMessage());
        }
    }

    private Map<String, Object> refundToMap(Refund refund) {
        Map<String, Object> row = new HashMap<>();
        row.put("id", refund.getId());
        row.put("refund_no", refund.getRefundNo());
        row.put("order_no", refund.getOrder().getOutTradeNo());
        row.put("amount", refund.getAmount());
        row.put("reason", refund.getReason());
        row.put("status", refund.getStatus());
        row.put("admin_note", refund.getAdminNote() == null ? "" : refund.getAdminNote());
        row.put("wallet_transaction_id", refund.getWalletTransactionId());
        row.put("created_at", refund.getCreatedAt());
        row.put("updated_at", refund.getUpdatedAt());
        row.put("reviewed_at", refund.getReviewedAt());
        return row;
    }
}
