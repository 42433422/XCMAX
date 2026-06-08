package com.modstore.repository;

import com.modstore.model.AccountExperienceLedger;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.Optional;

@Repository
public interface AccountExperienceLedgerRepository extends JpaRepository<AccountExperienceLedger, Long> {
    Optional<AccountExperienceLedger> findBySourceTypeAndSourceOrderId(String sourceType, String sourceOrderId);
}
