package com.modstore.repository;

import com.modstore.model.PlanTemplate;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;

@Repository
public interface PlanTemplateRepository extends JpaRepository<PlanTemplate, String> {
    List<PlanTemplate> findByActiveTrue();
}
