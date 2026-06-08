package com.modstore.job;

import com.modstore.service.OrderService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.time.Duration;

@Slf4j
@Component
@RequiredArgsConstructor
public class PendingOrderCleanupScheduler {

    private final OrderService orderService;

    @Value("${payment.pending-order-max-age-minutes:30}")
    private int maxAgeMinutes;

    @Scheduled(fixedRateString = "${payment.pending-order-cleanup-interval-ms:300000}")
    public void closeStalePendingOrders() {
        try {
            int closed = orderService.closeExpiredPendingOrders(Duration.ofMinutes(maxAgeMinutes));
            if (closed > 0) {
                log.info("Closed {} pending orders older than {} minutes", closed, maxAgeMinutes);
            }
        } catch (Exception e) {
            log.warn("Pending order cleanup failed", e);
        }
    }
}
