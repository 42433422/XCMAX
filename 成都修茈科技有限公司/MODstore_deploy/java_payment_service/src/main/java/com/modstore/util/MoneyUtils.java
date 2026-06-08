package com.modstore.util;

import java.math.BigDecimal;
import java.math.RoundingMode;

public final class MoneyUtils {

    private MoneyUtils() {
    }

    public static BigDecimal parse(Object value) {
        if (value == null) {
            return BigDecimal.ZERO.setScale(2, RoundingMode.HALF_UP);
        }
        return new BigDecimal(String.valueOf(value).trim()).setScale(2, RoundingMode.HALF_UP);
    }

    /**
     * 支付宝 {@code total_amount}：文档要求为 0 或两位小数；避免 {@code 10}、{@code 9.9} 等形态触发网关/验签异常。
     */
    public static String alipayTotalAmount(BigDecimal amount) {
        if (amount == null) {
            return "0.00";
        }
        return amount.setScale(2, RoundingMode.HALF_UP).toPlainString();
    }

    public static String amountSignString(BigDecimal value) {
        BigDecimal normalized = value == null ? BigDecimal.ZERO : value.stripTrailingZeros();
        if (normalized.scale() <= 0) {
            return normalized.toPlainString();
        }
        return normalized.setScale(Math.min(normalized.scale(), 6), RoundingMode.HALF_UP)
                .stripTrailingZeros()
                .toPlainString();
    }

    /** 解析 item_id 等整型字段，兼容 JSON Number / 字符串 / null。 */
    public static long asLong(Object value) {
        if (value == null) {
            return 0L;
        }
        if (value instanceof Number n) {
            return n.longValue();
        }
        String s = String.valueOf(value).trim();
        if (s.isEmpty() || "null".equalsIgnoreCase(s)) {
            return 0L;
        }
        return Long.parseLong(s);
    }

    /**
     * 会员/套餐单随单附赠的「Token 可用余额」元数：按实付金额（元）四舍五入为整数元；≤0 时返回 0。
     */
    public static int toIntYuanHalfUp(BigDecimal amount) {
        if (amount == null || amount.compareTo(BigDecimal.ZERO) <= 0) {
            return 0;
        }
        return amount.setScale(0, RoundingMode.HALF_UP).intValue();
    }
}
