package com.modstore.event;

import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.assertj.core.api.Assertions.assertThat;

class EventContractsTest {

    @Nested
    class CanonicalName {
        @Test
        void mapsLegacyAlias() {
            assertEquals("payment.paid", EventContracts.canonicalName("payment.order_paid"));
        }

        @Test
        void passthroughForKnownEvents() {
            assertEquals("refund.approved", EventContracts.canonicalName("refund.approved"));
            assertEquals("wallet.balance_changed", EventContracts.canonicalName("wallet.balance_changed"));
            assertEquals("refund.rejected", EventContracts.canonicalName("refund.rejected"));
            assertEquals("refund.failed", EventContracts.canonicalName("refund.failed"));
        }

        @Test
        void nullReturnsEmpty() {
            assertEquals("", EventContracts.canonicalName(null));
        }

        @Test
        void unknownEventPassthrough() {
            assertEquals("custom.event", EventContracts.canonicalName("custom.event"));
        }
    }

    @Nested
    class Version {
        @Test
        void v1EventsReturnVersionOne() {
            assertThat(EventContracts.version("payment.paid")).isEqualTo(1);
            assertThat(EventContracts.version("wallet.balance_changed")).isEqualTo(1);
            assertThat(EventContracts.version("refund.approved")).isEqualTo(1);
            assertThat(EventContracts.version("refund.rejected")).isEqualTo(1);
            assertThat(EventContracts.version("refund.failed")).isEqualTo(1);
        }

        @Test
        void unknownEventsReturnVersionOne() {
            assertThat(EventContracts.version("unknown.noop")).isEqualTo(1);
        }
    }

    @Nested
    class Constants {
        @Test
        void allEventTypesAreNonNull() {
            assertThat(EventContracts.PAYMENT_PAID).isNotNull().isNotBlank();
            assertThat(EventContracts.WALLET_BALANCE_CHANGED).isNotNull().isNotBlank();
            assertThat(EventContracts.REFUND_APPROVED).isNotNull().isNotBlank();
            assertThat(EventContracts.REFUND_REJECTED).isNotNull().isNotBlank();
            assertThat(EventContracts.REFUND_FAILED).isNotNull().isNotBlank();
        }

        @Test
        void legacyAliasIsDistinctFromCanonical() {
            assertThat(EventContracts.PAYMENT_ORDER_PAID_LEGACY)
                    .isNotEqualTo(EventContracts.PAYMENT_PAID);
        }
    }
}
