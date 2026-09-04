package com.modstore.service;

import com.modstore.model.AssetInstallCommand;
import com.modstore.model.CatalogItem;
import com.modstore.model.Order;
import com.modstore.model.Purchase;
import com.modstore.repository.AssetInstallCommandRepository;
import com.modstore.repository.CatalogItemRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.HexFormat;
import java.util.List;
import java.util.Optional;
import java.util.Set;

@Slf4j
@Service
@RequiredArgsConstructor
public class AssetInstallCommandService {

    private static final Set<String> INSTALLABLE_ARTIFACTS = Set.of("mod", "employee_pack", "bundle");

    private final AssetInstallCommandRepository commandRepository;
    private final CatalogItemRepository catalogItemRepository;

    /** Queue the same durable command consumed by the Python market API and XCAGI desktop. */
    public Optional<AssetInstallCommand> queuePaidItem(Order order, Purchase purchase) {
        if (order == null || purchase == null || purchase.getId() == null
                || order.getUser() == null || order.getUser().getId() == null
                || order.getItemId() == null || order.getItemId() <= 0) {
            return Optional.empty();
        }
        CatalogItem item = catalogItemRepository.findById(order.getItemId()).orElse(null);
        String artifact = item == null || item.getArtifact() == null
                ? "mod" : item.getArtifact().trim().toLowerCase();
        if (!INSTALLABLE_ARTIFACTS.contains(artifact)) {
            log.info("paid asset is download-only; install not queued order={} artifact={}",
                    order.getOutTradeNo(), artifact);
            return Optional.empty();
        }
        String artifactSha = item == null || item.getSha256() == null
                ? "" : item.getSha256().trim().toLowerCase();
        if (!artifactSha.matches("[0-9a-f]{64}")) {
            log.warn("paid item has no verifiable SHA256; install not queued order={}", order.getOutTradeNo());
            return Optional.empty();
        }

        String eventId = "payment.paid:" + order.getOutTradeNo();
        String material = "asset-install:" + order.getUser().getId() + ":" + purchase.getId()
                + ":*:payment_callback:" + eventId;
        String idempotencyKey = sha256Hex(material);
        Optional<AssetInstallCommand> existing = commandRepository.findByIdempotencyKey(idempotencyKey);
        if (existing.isPresent()) return existing;

        AssetInstallCommand command = new AssetInstallCommand();
        command.setUserId(order.getUser().getId());
        command.setPurchaseId(purchase.getId());
        command.setCatalogId(order.getItemId());
        command.setInstallationId("*");
        command.setIdempotencyKey(idempotencyKey);
        command.setSource("payment_callback");
        command.setSourceEventId(eventId);
        command.setStatus("pending");
        return Optional.of(commandRepository.save(command));
    }

    public int revokeForOrder(String orderNo) {
        String normalized = orderNo == null ? "" : orderNo.trim();
        if (normalized.isEmpty()) return 0;
        List<AssetInstallCommand> rows = commandRepository.findBySourceEventIdAndStatusIn(
                "payment.paid:" + normalized,
                List.of("pending", "failed", "claimed")
        );
        for (AssetInstallCommand command : rows) {
            command.setStatus("revoked");
            command.setError("payment_refunded");
        }
        commandRepository.saveAll(rows);
        return rows.size();
    }

    static String sha256Hex(String value) {
        try {
            return HexFormat.of().formatHex(
                    MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8))
            );
        } catch (Exception e) {
            throw new IllegalStateException("SHA-256 unavailable", e);
        }
    }
}
