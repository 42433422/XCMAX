package com.modstore.model;

import jakarta.persistence.*;
import lombok.Data;

import java.time.LocalDateTime;

@Data
@Entity
@Table(
        name = "asset_install_commands",
        uniqueConstraints = @UniqueConstraint(
                name = "uq_asset_install_command_idempotency",
                columnNames = "idempotency_key"
        )
)
public class AssetInstallCommand {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "user_id", nullable = false)
    private Long userId;

    @Column(name = "purchase_id", nullable = false)
    private Long purchaseId;

    @Column(name = "catalog_id", nullable = false)
    private Long catalogId;

    @Column(name = "installation_id", nullable = false, length = 64)
    private String installationId = "*";

    @Column(name = "idempotency_key", nullable = false, length = 192)
    private String idempotencyKey;

    @Column(name = "source", nullable = false, length = 32)
    private String source = "payment_callback";

    @Column(name = "source_event_id", nullable = false, length = 192)
    private String sourceEventId = "";

    @Column(name = "status", nullable = false, length = 32)
    private String status = "pending";

    @Column(name = "attempt_count", nullable = false)
    private int attemptCount = 0;

    @Column(name = "result_json", nullable = false, columnDefinition = "TEXT")
    private String resultJson = "{}";

    @Column(name = "error", nullable = false, columnDefinition = "TEXT")
    private String error = "";

    @Column(name = "claimed_at")
    private LocalDateTime claimedAt;

    @Column(name = "completed_at")
    private LocalDateTime completedAt;

    @Column(name = "created_at", nullable = false)
    private LocalDateTime createdAt;

    @Column(name = "updated_at", nullable = false)
    private LocalDateTime updatedAt;

    @PrePersist
    protected void onCreate() {
        LocalDateTime now = LocalDateTime.now();
        if (createdAt == null) createdAt = now;
        updatedAt = now;
    }

    @PreUpdate
    protected void onUpdate() {
        updatedAt = LocalDateTime.now();
    }
}
