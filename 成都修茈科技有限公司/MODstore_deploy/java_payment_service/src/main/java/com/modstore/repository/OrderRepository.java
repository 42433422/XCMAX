package com.modstore.repository;

import com.modstore.model.Order;
import com.modstore.model.User;
import jakarta.persistence.LockModeType;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Lock;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import java.util.List;
import java.util.Optional;

@Repository
public interface OrderRepository extends JpaRepository<Order, Long> {
    Optional<Order> findByOutTradeNo(String outTradeNo);
    Optional<Order> findByTradeNo(String tradeNo);

    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query("SELECT o FROM Order o WHERE o.outTradeNo = ?1")
    Optional<Order> findByOutTradeNoForUpdate(String outTradeNo);
    
    @Query("SELECT o FROM Order o WHERE o.user = ?1 ORDER BY o.createdAt DESC")
    List<Order> findByUserOrderByCreatedAtDesc(User user);

    @Query("SELECT o FROM Order o WHERE o.user = ?1 ORDER BY o.createdAt DESC")
    List<Order> findByUserOrderByCreatedAtDesc(User user, Pageable pageable);
    
    @Query("SELECT o FROM Order o WHERE o.user = ?1 AND o.status = ?2 ORDER BY o.createdAt DESC")
    List<Order> findByUserAndStatusOrderByCreatedAtDesc(User user, String status);

    @Query("SELECT o FROM Order o WHERE o.user = ?1 AND o.status = ?2 ORDER BY o.createdAt DESC")
    List<Order> findByUserAndStatusOrderByCreatedAtDesc(User user, String status, Pageable pageable);
    
    @Query("SELECT COUNT(o) FROM Order o WHERE o.user = ?1")
    long countByUser(User user);
    
    @Query("SELECT COUNT(o) FROM Order o WHERE o.user = ?1 AND o.status = ?2")
    long countByUserAndStatus(User user, String status);

    /**
     * 用户订单列表：隐藏已「一键清理」的终态单；待支付、已支付、退款中 仍展示。
     */
    @Query("SELECT o FROM Order o WHERE o.user = :user "
            + "AND (o.dismissedByUser = false OR o.status IN ('pending', 'paid', 'refunding')) "
            + "AND (:status IS NULL OR o.status = :status) "
            + "ORDER BY o.createdAt DESC")
    List<Order> findVisibleByUserAndOptionalStatus(
            @Param("user") User user,
            @Param("status") String status,
            Pageable pageable
    );

    @Query("SELECT COUNT(o) FROM Order o WHERE o.user = :user "
            + "AND (o.dismissedByUser = false OR o.status IN ('pending', 'paid', 'refunding')) "
            + "AND (:status IS NULL OR o.status = :status)")
    long countVisibleByUserAndOptionalStatus(@Param("user") User user, @Param("status") String status);

    @Modifying(clearAutomatically = true, flushAutomatically = true)
    @Query("UPDATE Order o SET o.dismissedByUser = true WHERE o.user = :user "
            + "AND o.status NOT IN ('pending', 'paid', 'refunding')")
    int markDismissedForNonActiveOrders(@Param("user") User user);

    /**
     * 已履约、仍为「已支付」的会员套餐单（已全额退款/部分退款的单状态非 paid，不纳入补发）。
     */
    List<Order> findByOrderKindAndFulfilledTrueAndStatus(String orderKind, String status);

    List<Order> findByStatusAndCreatedAtBefore(String status, java.time.LocalDateTime before);
}
