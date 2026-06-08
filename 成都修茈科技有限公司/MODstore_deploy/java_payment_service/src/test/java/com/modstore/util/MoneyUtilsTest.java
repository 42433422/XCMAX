package com.modstore.util;

import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class MoneyUtilsTest {

    @Nested
    class ToIntYuanHalfUp {
        @Test
        void roundsToIntegerYuan() {
            assertThat(MoneyUtils.toIntYuanHalfUp(new BigDecimal("9.40"))).isEqualTo(9);
            assertThat(MoneyUtils.toIntYuanHalfUp(new BigDecimal("9.50"))).isEqualTo(10);
            assertThat(MoneyUtils.toIntYuanHalfUp(new BigDecimal("9.90"))).isEqualTo(10);
            assertThat(MoneyUtils.toIntYuanHalfUp(new BigDecimal("199.00"))).isEqualTo(199);
            assertThat(MoneyUtils.toIntYuanHalfUp(null)).isEqualTo(0);
            assertThat(MoneyUtils.toIntYuanHalfUp(BigDecimal.ZERO)).isEqualTo(0);
        }

        @Test
        void negativeAmountReturnsZero() {
            assertThat(MoneyUtils.toIntYuanHalfUp(new BigDecimal("-5.00"))).isEqualTo(0);
        }

        @Test
        void largeAmount() {
            assertThat(MoneyUtils.toIntYuanHalfUp(new BigDecimal("999999.99"))).isEqualTo(1000000);
        }

        @Test
        void fractionalCents() {
            assertThat(MoneyUtils.toIntYuanHalfUp(new BigDecimal("0.49"))).isEqualTo(0);
            assertThat(MoneyUtils.toIntYuanHalfUp(new BigDecimal("0.50"))).isEqualTo(1);
        }
    }

    @Nested
    class Parse {
        @Test
        void parsesStringToBigDecimal() {
            assertThat(MoneyUtils.parse("10.50")).isEqualByComparingTo(new BigDecimal("10.50"));
            assertThat(MoneyUtils.parse("0")).isEqualByComparingTo(BigDecimal.ZERO);
        }

        @Test
        void nullReturnsZero() {
            assertThat(MoneyUtils.parse(null)).isEqualByComparingTo(BigDecimal.ZERO);
        }

        @Test
        void parsesNumber() {
            assertThat(MoneyUtils.parse(42)).isEqualByComparingTo(new BigDecimal("42.00"));
        }

        @Test
        void trimsWhitespace() {
            assertThat(MoneyUtils.parse("  9.90  ")).isEqualByComparingTo(new BigDecimal("9.90"));
        }
    }

    @Nested
    class AlipayTotalAmount {
        @Test
        void formatsWithTwoDecimals() {
            assertThat(MoneyUtils.alipayTotalAmount(new BigDecimal("10"))).isEqualTo("10.00");
            assertThat(MoneyUtils.alipayTotalAmount(new BigDecimal("9.9"))).isEqualTo("9.90");
            assertThat(MoneyUtils.alipayTotalAmount(new BigDecimal("9.90"))).isEqualTo("9.90");
        }

        @Test
        void nullReturnsZero() {
            assertThat(MoneyUtils.alipayTotalAmount(null)).isEqualTo("0.00");
        }
    }

    @Nested
    class AmountSignString {
        @Test
        void stripsTrailingZeros() {
            assertThat(MoneyUtils.amountSignString(new BigDecimal("10.00"))).isEqualTo("10");
            assertThat(MoneyUtils.amountSignString(new BigDecimal("9.90"))).isEqualTo("9.9");
        }

        @Test
        void nullReturnsZero() {
            assertThat(MoneyUtils.amountSignString(null)).isEqualTo("0");
        }
    }

    @Nested
    class AsLong {
        @Test
        void parsesVariousTypes() {
            assertThat(MoneyUtils.asLong(42L)).isEqualTo(42L);
            assertThat(MoneyUtils.asLong(42)).isEqualTo(42L);
            assertThat(MoneyUtils.asLong("42")).isEqualTo(42L);
        }

        @Test
        void nullReturnsZero() {
            assertThat(MoneyUtils.asLong(null)).isEqualTo(0L);
        }

        @Test
        void blankStringReturnsZero() {
            assertThat(MoneyUtils.asLong("")).isEqualTo(0L);
            assertThat(MoneyUtils.asLong("null")).isEqualTo(0L);
        }
    }
}
