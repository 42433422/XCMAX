package com.modstore.model;

import jakarta.persistence.*;
import lombok.Data;

import java.time.LocalDateTime;

@Data
@Entity
@Table(name = "quotas", uniqueConstraints = @UniqueConstraint(name = "uq_user_quota_type", columnNames = {"user_id", "quota_type"}))
public class Quota {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @ManyToOne
    @JoinColumn(name = "user_id", nullable = false)
    private User user;

    @Column(name = "quota_type", nullable = false, length = 64)
    private String quotaType;

    @Column(name = "total", nullable = false)
    private int total;

    @Column(name = "used", nullable = false)
    private int used;

    @Column(name = "reset_at")
    private LocalDateTime resetAt;

    @Column(name = "updated_at")
    private LocalDateTime updatedAt;

    @PrePersist
    @PreUpdate
    protected void onUpdate() {
        updatedAt = LocalDateTime.now();
    }
}
