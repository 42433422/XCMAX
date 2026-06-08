package com.modstore.model;

import jakarta.persistence.*;
import lombok.Data;

import java.time.LocalDateTime;

@Data
@Entity
@Table(
    name = "entitlements",
    indexes = {
        @Index(name = "idx_entitlements_user_active", columnList = "user_id, is_active"),
        @Index(name = "idx_entitlements_source_order", columnList = "source_order_id")
    }
)
public class Entitlement {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @ManyToOne
    @JoinColumn(name = "user_id", nullable = false)
    private User user;

    @Column(name = "catalog_id")
    private Long catalogId;

    @Column(name = "entitlement_type", nullable = false, length = 32)
    private String entitlementType;

    @Column(name = "source_order_id", length = 64)
    private String sourceOrderId = "";

    @Column(name = "metadata_json", columnDefinition = "TEXT")
    private String metadataJson = "{}";

    @Column(name = "granted_at")
    private LocalDateTime grantedAt;

    @Column(name = "expires_at")
    private LocalDateTime expiresAt;

    @Column(name = "is_active", nullable = false)
    private boolean active = true;

    @PrePersist
    protected void onCreate() {
        if (grantedAt == null) grantedAt = LocalDateTime.now();
    }
}
