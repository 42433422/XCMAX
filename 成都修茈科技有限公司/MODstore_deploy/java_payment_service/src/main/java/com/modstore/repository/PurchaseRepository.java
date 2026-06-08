package com.modstore.repository;

import com.modstore.model.Purchase;
import com.modstore.model.User;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.stereotype.Repository;

import java.util.List;

@Repository
public interface PurchaseRepository extends JpaRepository<Purchase, Long> {
    boolean existsByUserAndCatalogId(User user, Long catalogId);

    @Query("SELECT p FROM Purchase p WHERE p.user = ?1 ORDER BY p.createdAt DESC")
    List<Purchase> findByUserOrderByCreatedAtDesc(User user);
    
    @Query("SELECT COUNT(p) FROM Purchase p WHERE p.user = ?1")
    long countByUser(User user);
}
