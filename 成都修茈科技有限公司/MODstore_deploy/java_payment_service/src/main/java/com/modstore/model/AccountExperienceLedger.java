package com.modstore.model;

import jakarta.persistence.*;
import lombok.Data;

import java.math.BigDecimal;
import java.time.LocalDateTime;

@Data
@Entity
@Table(
    name = "account_experience_ledger",
    uniqueConstraints = {
        @UniqueConstraint(name = "uq_account_xp_source", columnNames = {"source_type", "source_order_id"})
    },
    indexes = {
        @Index(name = "idx_account_xp_user", columnList = "user_id")
    }
)
public class AccountExperienceLedger {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "user_id", nullable = false)
    private Long userId;

    @Column(name = "source_type", nullable = false, length = 32)
    private String sourceType;

    @Column(name = "source_order_id", nullable = false, length = 64)
    private String sourceOrderId;

    @Column(name = "amount", nullable = false)
    private BigDecimal amount;

    @Column(name = "xp_delta", nullable = false)
    private long xpDelta;

    @Column(name = "description", columnDefinition = "TEXT")
    private String description;

    @Column(name = "created_at", nullable = false, columnDefinition = "TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
    private LocalDateTime createdAt;

    @PrePersist
    protected void onCreate() {
        if (createdAt == null) {
            createdAt = LocalDateTime.now();
        }
    }
}
