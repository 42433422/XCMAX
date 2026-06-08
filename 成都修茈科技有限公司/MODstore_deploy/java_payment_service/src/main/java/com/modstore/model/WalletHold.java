package com.modstore.model;

import jakarta.persistence.*;
import lombok.Data;

import java.math.BigDecimal;
import java.time.LocalDateTime;

@Data
@Entity
@Table(name = "wallet_holds")
public class WalletHold {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @ManyToOne
    @JoinColumn(name = "user_id", nullable = false)
    private User user;

    @Column(name = "hold_no", nullable = false, unique = true, length = 64)
    private String holdNo;

    @Column(name = "amount", nullable = false, precision = 12, scale = 2)
    private BigDecimal amount;

    @Column(name = "settled_amount", nullable = false, precision = 12, scale = 2)
    private BigDecimal settledAmount = BigDecimal.ZERO;

    @Column(name = "status", nullable = false, length = 24)
    private String status = "held";

    @Column(name = "provider", length = 64)
    private String provider;

    @Column(name = "model", length = 128)
    private String model;

    @Column(name = "request_id", length = 128)
    private String requestId;

    @Column(name = "idempotency_key", nullable = false, unique = true, length = 128)
    private String idempotencyKey;

    @Column(name = "preauth_transaction_id")
    private Long preauthTransactionId;

    @Column(name = "settlement_transaction_id")
    private Long settlementTransactionId;

    @Column(name = "created_at", nullable = false)
    private LocalDateTime createdAt;

    @Column(name = "expires_at")
    private LocalDateTime expiresAt;

    @Column(name = "settled_at")
    private LocalDateTime settledAt;

    @Column(name = "released_at")
    private LocalDateTime releasedAt;

    @PrePersist
    protected void onCreate() {
        LocalDateTime now = LocalDateTime.now();
        createdAt = now;
        if (expiresAt == null) {
            expiresAt = now.plusMinutes(10);
        }
    }
}
