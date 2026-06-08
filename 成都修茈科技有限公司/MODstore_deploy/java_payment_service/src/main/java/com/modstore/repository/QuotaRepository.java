package com.modstore.repository;

import com.modstore.model.Quota;
import com.modstore.model.User;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;
import java.util.Optional;

@Repository
public interface QuotaRepository extends JpaRepository<Quota, Long> {
    List<Quota> findByUser(User user);
    Optional<Quota> findByUserAndQuotaType(User user, String quotaType);
}
