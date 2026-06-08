package com.modstore.model;

import jakarta.persistence.*;
import lombok.Data;

import java.time.LocalDateTime;

@Data
@Entity
@Table(
    name = "user_plans",
    indexes = {
        @Index(name = "idx_user_plans_user_active", columnList = "user_id, is_active"),
        @Index(name = "idx_user_plans_source_order", columnList = "source_order_id")
    }
)
public class UserPlan {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @ManyToOne
    @JoinColumn(name = "user_id", nullable = false)
    private User user;

    @ManyToOne
    @JoinColumn(name = "plan_id", nullable = false)
    private PlanTemplate plan;

    @Column(name = "source_order_id", length = 64)
    private String sourceOrderId = "";

    @Column(name = "started_at")
    private LocalDateTime startedAt;

    @Column(name = "expires_at")
    private LocalDateTime expiresAt;

    @Column(name = "is_active", nullable = false)
    private boolean active = true;

    @Column(name = "created_at")
    private LocalDateTime createdAt;

    @PrePersist
    protected void onCreate() {
        if (startedAt == null) startedAt = LocalDateTime.now();
        if (createdAt == null) createdAt = LocalDateTime.now();
    }
}
