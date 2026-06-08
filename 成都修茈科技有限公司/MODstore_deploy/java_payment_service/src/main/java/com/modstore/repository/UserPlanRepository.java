package com.modstore.repository;

import com.modstore.model.User;
import com.modstore.model.UserPlan;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;
import java.util.Optional;

@Repository
public interface UserPlanRepository extends JpaRepository<UserPlan, Long> {
    Optional<UserPlan> findFirstByUserAndActiveTrueOrderByStartedAtDesc(User user);

    List<UserPlan> findByUserAndActiveTrue(User user);

    Optional<UserPlan> findByUserAndSourceOrderId(User user, String sourceOrderId);
}
