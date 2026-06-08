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

    @Column(name = "experience", nullable = false, columnDefinition = "INTEGER DEFAULT 0")
    private long experience;

    @Column(name = "created_at", nullable = false, columnDefinition = "TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
    private LocalDateTime createdAt;
    
    @PrePersist
    protected void onCreate() {
        createdAt = LocalDateTime.now();
    }
}
