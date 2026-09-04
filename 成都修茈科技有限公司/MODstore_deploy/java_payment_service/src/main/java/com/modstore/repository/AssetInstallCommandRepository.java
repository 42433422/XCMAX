package com.modstore.repository;

import com.modstore.model.AssetInstallCommand;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;
import java.util.Optional;

@Repository
public interface AssetInstallCommandRepository extends JpaRepository<AssetInstallCommand, Long> {
    Optional<AssetInstallCommand> findByIdempotencyKey(String idempotencyKey);
    List<AssetInstallCommand> findBySourceEventIdAndStatusIn(String sourceEventId, List<String> statuses);
}
