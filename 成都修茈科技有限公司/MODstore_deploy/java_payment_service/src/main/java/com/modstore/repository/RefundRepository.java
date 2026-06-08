package com.modstore.repository;

import com.modstore.model.Order;
import com.modstore.model.Refund;
import com.modstore.model.User;
import jakarta.persistence.LockModeType;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Lock;
import org.springframework.data.jpa.repository.Query;
import org.springframework.stereotype.Repository;

import java.util.Collection;
import java.util.List;
import java.util.Optional;

@Repository
public interface RefundRepository extends JpaRepository<Refund, Long> {
    Optional<Refund> findByRefundNo(String refundNo);

    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query("SELECT r FROM Refund r WHERE r.id = ?1")
    Optional<Refund> findByIdForUpdate(Long id);

    Optional<Refund> findFirstByOrderAndStatusIn(Order order, Collection<String> statuses);

    List<Refund> findByUserOrderByCreatedAtDesc(User user, Pageable pageable);

    long countByUser(User user);

    List<Refund> findByStatusOrderByCreatedAtAsc(String status, Pageable pageable);
}
