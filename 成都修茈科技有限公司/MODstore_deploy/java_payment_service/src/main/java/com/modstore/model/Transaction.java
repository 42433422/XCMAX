package com.modstore.model;

import jakarta.persistence.*;
import lombok.Data;
import java.math.BigDecimal;
import java.time.LocalDateTime;

@Data
@Entity
@Table(name = "transactions")
public class Transaction {
    
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;
    
    @ManyToOne
    @JoinColumn(name = "user_id", nullable = false)
    private User user;
    
    @Column(name = "amount", nullable = false, precision = 12, scale = 2)
    private BigDecimal amount;

    @Column(name = "balance_before", nullable = false, precision = 12, scale = 2)
    private BigDecimal balanceBefore = BigDecimal.ZERO;

    @Column(name = "balance_after", nullable = false, precision = 12, scale = 2)
    private BigDecimal balanceAfter = BigDecimal.ZERO;
    
    @Column(name = "txn_type", nullable = false, length = 32)
    private String transactionType;
    
    @Column(name = "status", nullable = false, length = 16, columnDefinition = "VARCHAR(16) DEFAULT 'completed'")
    private String status;
    
    @Column(name = "description", columnDefinition = "TEXT DEFAULT ''")
    private String description;

    @Column(name = "reference_no", length = 64)
    private String referenceNo;

    @Column(name = "order_no", length = 64)
    private String orderNo;

    @Column(name = "refund_no", length = 64)
    private String refundNo;

    @Column(name = "idempotency_key", unique = true, length = 128)
    private String idempotencyKey;
    
    @Column(name = "created_at", nullable = false, columnDefinition = "TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
    private LocalDateTime createdAt;
    
    @PrePersist
    protected void onCreate() {
        createdAt = LocalDateTime.now();
    }
}
