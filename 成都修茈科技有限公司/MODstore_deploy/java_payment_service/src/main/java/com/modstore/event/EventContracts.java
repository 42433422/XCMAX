package com.modstore.event;

import java.util.Map;
import java.util.Set;

public final class EventContracts {
    public static final String PAYMENT_PAID = "payment.paid";
    public static final String PAYMENT_ORDER_PAID_LEGACY = "payment.order_paid";
    public static final String WALLET_BALANCE_CHANGED = "wallet.balance_changed";
    public static final String REFUND_APPROVED = "refund.approved";
    public static final String REFUND_REJECTED = "refund.rejected";
    public static final String REFUND_FAILED = "refund.failed";

    private static final Map<String, String> ALIASES = Map.of(
            PAYMENT_ORDER_PAID_LEGACY, PAYMENT_PAID
    );

    private static final Set<String> V1_EVENTS = Set.of(
            PAYMENT_PAID,
            WALLET_BALANCE_CHANGED,
            REFUND_APPROVED,
            REFUND_REJECTED,
            REFUND_FAILED
    );

    private EventContracts() {
    }

    public static String canonicalName(String eventType) {
        if (eventType == null) {
            return "";
        }
        return ALIASES.getOrDefault(eventType, eventType);
    }

    public static int version(String eventType) {
        return V1_EVENTS.contains(canonicalName(eventType)) ? 1 : 1;
    }
}
