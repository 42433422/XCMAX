package com.modstore.repository;

import com.modstore.model.WalletHold;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.Optional;

@Repository
public interface WalletHoldRepository extends JpaRepository<WalletHold, Long> {
    Optional<WalletHold> findByHoldNo(String holdNo);
    Optional<WalletHold> findByIdempotencyKey(String idempotencyKey);
}
