package com.modstore.service;

import com.modstore.model.Order;
import com.modstore.model.User;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 账号等级与经验体系：纯静态方法的单元测试。
 * 与 Python {@code tests/test_account_level.py::test_xp_from_amount_one_yuan_equals_100} 对齐。
 */
class AccountLevelServiceTest {

    @Test
    void xpFromAmountOneYuanEqualsHundredXp() {
        assertThat(AccountLevelService.xpFromAmount(BigDecimal.ONE)).isEqualTo(100L);
        assertThat(AccountLevelService.xpFromAmount(new BigDecimal("12.34"))).isEqualTo(1234L);
        assertThat(AccountLevelService.xpFromAmount(new BigDecimal("0.99"))).isEqualTo(99L);
        assertThat(AccountLevelService.xpFromAmount(BigDecimal.ZERO)).isEqualTo(0L);
        assertThat(AccountLevelService.xpFromAmount(new BigDecimal("-5"))).isEqualTo(0L);
        assertThat(AccountLevelService.xpFromAmount(null)).isEqualTo(0L);
    }

    @Test
    void itemPlanAndWalletOrdersAreAllCountable() {
        User user = new User();
        user.setId(1L);

        assertThat(AccountLevelService.isCountable(buildOrder(user, "item", "10.00", 1L, null))).isTrue();
        assertThat(AccountLevelService.isCountable(buildOrder(user, "plan", "10.00", null, "plan_pro"))).isTrue();
        assertThat(AccountLevelService.isCountable(buildOrder(user, " wallet ", "10.00", null, null))).isTrue();
        assertThat(AccountLevelService.isCountable(buildOrder(user, "wallet", "10.00", null, null))).isTrue();
        assertThat(AccountLevelService.isCountable(buildOrder(user, " ", "10.00", 5L, null))).isTrue();
        assertThat(AccountLevelService.isCountable(buildOrder(user, "", "10.00", null, null))).isFalse();
        assertThat(AccountLevelService.isCountable(null)).isFalse();
    }

    private Order buildOrder(
            User user, String kind, String amount, Long itemId, String planId) {
        Order order = new Order();
        order.setUser(user);
        order.setOrderKind(kind);
        order.setOutTradeNo("UT-" + System.nanoTime());
        order.setTotalAmount(new BigDecimal(amount));
        order.setItemId(itemId);
        order.setPlanId(planId);
        return order;
    }
}
