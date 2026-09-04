package com.modstore.model;

import jakarta.persistence.*;
import lombok.Data;
import java.time.LocalDateTime;

@Data
@Entity
@Table(name = "users")
public class User {
    
    @Id
    private Long id;
    
    @Column(name = "username", unique = true, nullable = false, length = 64)
    private String username;
    
    @Column(name = "email", unique = true, length = 128)
    private String email;

    @Column(name = "phone", unique = true, length = 32)
    private String phone;
    
    @Column(name = "password_hash", nullable = false, length = 256)
    private String passwordHash;
    
    @Column(name = "is_admin", nullable = false, columnDefinition = "BOOLEAN DEFAULT false")
    private boolean admin;

    @Column(name = "is_enterprise", nullable = false, columnDefinition = "BOOLEAN DEFAULT false")
    private boolean enterprise;

    /**
     * Internal, verified legal-entity identity.  This is deliberately separate
     * from username/company display text and is never returned by public APIs.
     */
    @Column(name = "enterprise_subject_id", length = 128)
    private String enterpriseSubjectId;

    @Column(name = "enterprise_legal_name", length = 256)
    private String enterpriseLegalName;

    @Column(name = "enterprise_verification_sha256", length = 64)
    private String enterpriseVerificationSha256;

    @Column(name = "enterprise_verified_at")
    private LocalDateTime enterpriseVerifiedAt;

    @Column(name = "enterprise_verified_by_user_id")
    private Long enterpriseVerifiedByUserId;

    @Column(name = "account_state", nullable = false, length = 32,
            columnDefinition = "VARCHAR(32) DEFAULT 'pending_plan'")
    private String accountState = "pending_plan";

    @Column(name = "experience", nullable = false, columnDefinition = "INTEGER DEFAULT 0")
    private long experience;

    @Column(name = "created_at", nullable = false, columnDefinition = "TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
    private LocalDateTime createdAt;
    
    @PrePersist
    protected void onCreate() {
        createdAt = LocalDateTime.now();
    }
}
