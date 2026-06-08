package com.modstore.repository;

import com.modstore.model.Entitlement;
import com.modstore.model.User;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;
import java.util.Optional;

@Repository
public interface EntitlementRepository extends JpaRepository<Entitlement, Long> {
    List<Entitlement> findByUserAndActiveTrueOrderByGrantedAtDesc(User user);

    boolean existsByUserAndCatalogIdAndActiveTrue(User user, Long catalogId);

    Optional<Entitlement> findBySourceOrderId(String sourceOrderId);
}
