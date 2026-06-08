package com.modstore.model;

import jakarta.persistence.*;
import lombok.Data;

import java.math.BigDecimal;
import java.time.LocalDateTime;

@Data
@Entity
@Table(name = "catalog_items")
public class CatalogItem {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "pkg_id", unique = true, nullable = false, length = 128)
    private String pkgId;

    @Column(name = "version", nullable = false, length = 32)
    private String version = "1.0.0";

    @Column(name = "name", nullable = false, length = 256)
    private String name;

    @Column(name = "description", columnDefinition = "TEXT")
    private String description = "";

    @Column(name = "price", nullable = false, precision = 12, scale = 2)
    private BigDecimal price = BigDecimal.ZERO;

    @Column(name = "author_id")
    private Long authorId;

    @Column(name = "artifact", length = 32)
    private String artifact = "mod";

    @Column(name = "industry", length = 64)
    private String industry = "通用";

    @Column(name = "stored_filename", length = 256)
    private String storedFilename = "";

    @Column(name = "sha256", length = 64)
    private String sha256 = "";

    @Column(name = "is_public", nullable = false)
    private boolean publicItem = true;

    @Column(name = "security_level", length = 32)
    private String securityLevel = "personal";

    @Column(name = "industry_code", length = 16)
    private String industryCode = "";

    @Column(name = "industry_secondary", length = 64)
    private String industrySecondary = "";

    @Column(name = "description_embedding", columnDefinition = "TEXT")
    private String descriptionEmbedding = "";

    @Column(name = "created_at")
    private LocalDateTime createdAt;

    @PrePersist
    protected void onCreate() {
        if (createdAt == null) createdAt = LocalDateTime.now();
    }
}
