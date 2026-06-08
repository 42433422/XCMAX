package com.modstore.repository;

import com.modstore.model.Transaction;
import com.modstore.model.User;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import java.math.BigDecimal;
import java.util.List;
import java.util.Optional;

@Repository
public interface TransactionRepository extends JpaRepository<Transaction, Long> {
    @Query("SELECT t FROM Transaction t WHERE t.user = ?1 ORDER BY t.createdAt DESC")
    List<Transaction> findByUserOrderByCreatedAtDesc(User user);

    @Query("SELECT t FROM Transaction t WHERE t.user = ?1 ORDER BY t.createdAt DESC")
    List<Transaction> findByUserOrderByCreatedAtDesc(User user, Pageable pageable);
    
    @Query("SELECT COUNT(t) FROM Transaction t WHERE t.user = ?1")
    long countByUser(User user);

    Optional<Transaction> findByIdempotencyKey(String idempotencyKey);

    @Query("SELECT t FROM Transaction t WHERE t.user = ?1 AND t.orderNo = ?2 ORDER BY t.createdAt DESC")
    List<Transaction> findByUserAndOrderNoOrderByCreatedAtDesc(User user, String orderNo);

    /** 会员随单赠送入金 + 退款扣回，净值（元，可正可负；由调用方取整与下限 0） */
    @Query("SELECT COALESCE(SUM(t.amount), 0) FROM Transaction t WHERE t.user = :user AND t.transactionType IN ('plan_membership_tokens', 'plan_membership_tokens_revoke')")
    BigDecimal sumMembershipReferenceNet(@Param("user") User user);
}
