package com.modstore.model;

import jakarta.persistence.*;
import lombok.Data;
import java.math.BigDecimal;
import java.time.LocalDateTime;

@Data
@Entity
@Table(
    name = "orders",
    indexes = {
        @Index(name = "idx_orders_user_created", columnList = "user_id, created_at"),
        @Index(name = "idx_orders_status", columnList = "status"),
        @Index(name = "idx_orders_trade_no", columnList = "trade_no")
    }
)
public class Order {
    
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;
    
    @Column(name = "out_trade_no", unique = true, nullable = false, length = 64)
    private String outTradeNo;
    
    @Column(name = "trade_no", length = 64)
    private String tradeNo;
    
    @ManyToOne
    @JoinColumn(name = "user_id", nullable = false)
    private User user;
    
    @Column(name = "subject", nullable = false, length = 256)
    private String subject;
    
    @Column(name = "total_amount", nullable = false, precision = 12, scale = 2)
    private BigDecimal totalAmount;
    
    @Column(name = "order_kind", nullable = false, length = 32)
    private String orderKind;
    
    @Column(name = "item_id")
    private Long itemId;
    
    @Column(name = "plan_id", length = 64)
    private String planId;
    
    @Column(name = "status", nullable = false, length = 32, columnDefinition = "VARCHAR(32) DEFAULT 'pending'")
    private String status;
    
    @Column(name = "buyer_id", length = 64)
    private String buyerId;
    
    @Column(name = "paid_at")
    private LocalDateTime paidAt;
    
    @Column(name = "fulfilled", nullable = false, columnDefinition = "BOOLEAN DEFAULT false")
    private boolean fulfilled;

    @Column(name = "refunded_amount", nullable = false, precision = 12, scale = 2)
    private BigDecimal refundedAmount = BigDecimal.ZERO;

    @Column(name = "refund_status", nullable = false, length = 32, columnDefinition = "VARCHAR(32) DEFAULT 'none'")
    private String refundStatus = "none";

    @Column(name = "refunded_at")
    private LocalDateTime refundedAt;

    @Column(name = "qr_code", columnDefinition = "TEXT")
    private String qrCode;

    @Column(name = "pay_type", length = 32)
    private String payType;

    @Column(name = "request_id", unique = true, length = 64)
    private String requestId;

    /**
     * 为 true 时，在「我的订单/最近订单」列表中隐藏，仅对非进行中单生效（需配合查询条件）。
     * 待支付、已支付、退款中 永不标记为隐藏；实体记录仍保留。
     */
    @Column(name = "dismissed_by_user", nullable = false, columnDefinition = "BOOLEAN DEFAULT false")
    private boolean dismissedByUser = false;
    
    @Column(name = "created_at", nullable = false, columnDefinition = "TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
    private LocalDateTime createdAt;
    
    @Column(name = "updated_at", nullable = false, columnDefinition = "TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
    private LocalDateTime updatedAt;
    
    @PrePersist
    protected void onCreate() {
        if (createdAt == null) {
            createdAt = LocalDateTime.now();
        }
        if (refundedAmount == null) {
            refundedAmount = BigDecimal.ZERO;
        }
        if (refundStatus == null || refundStatus.isBlank()) {
            refundStatus = "none";
        }
        updatedAt = LocalDateTime.now();
    }

    @PreUpdate
    protected void onUpdate() {
        updatedAt = LocalDateTime.now();
    }
}
