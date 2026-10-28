package com.modstore.repository;

import com.modstore.model.WalletHold;
import jakarta.persistence.LockModeType;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Lock;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import java.util.Optional;

@Repository
public interface WalletHoldRepository extends JpaRepository<WalletHold, Long> {
    Optional<WalletHold> findByHoldNo(String holdNo);
    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query("select h from WalletHold h where h.holdNo = :holdNo")
    Optional<WalletHold> findByHoldNoForUpdate(@Param("holdNo") String holdNo);
    Optional<WalletHold> findByIdempotencyKey(String idempotencyKey);
}
