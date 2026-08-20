package com.modstore.controller;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.modstore.model.Order;
import com.modstore.model.Refund;
import com.modstore.model.Transaction;
import com.modstore.model.User;
import com.modstore.model.Wallet;
import com.modstore.model.WalletHold;
import com.modstore.service.CurrentUserService;
import com.modstore.service.OrderService;
import com.modstore.service.RefundService;
import com.modstore.service.WalletService;
import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.web.server.ResponseStatusException;

class WalletControllerContractTest {

    private WalletService walletService;
    private CurrentUserService currentUserService;
    private OrderService orderService;
    private RefundService refundService;
    private WalletController controller;
    private User user;

    @BeforeEach
    void setUp() {
        walletService = mock(WalletService.class);
        currentUserService = mock(CurrentUserService.class);
        orderService = mock(OrderService.class);
        refundService = mock(RefundService.class);
        controller = new WalletController(walletService, currentUserService, orderService, refundService);
        user = new User();
        user.setId(8L);
        when(currentUserService.requireCurrentUser()).thenReturn(user);
        when(walletService.getMembershipReferenceLineYuan(user)).thenReturn(199);
        when(walletService.getBalance(user)).thenReturn(new BigDecimal("88.00"));
    }

    @Test
    void balanceSupportsExistingEmptyAndUnavailableWallets() {
        Wallet wallet = new Wallet();
        wallet.setBalance(new BigDecimal("88.00"));
        wallet.setUpdatedAt(LocalDateTime.now());
        when(walletService.getWallet(user)).thenReturn(Optional.of(wallet));
        assertEquals(new BigDecimal("88.00"), controller.getWallet().get("balance"));

        when(walletService.getWallet(user)).thenReturn(Optional.empty());
        assertEquals(BigDecimal.ZERO, controller.getBalance().get("balance"));

        when(currentUserService.requireCurrentUser()).thenThrow(new IllegalStateException("no user"));
        assertFalse((Boolean) controller.getBalance().get("ok"));
    }

    @Test
    void tokenRechargeRequiresAdminConfigurationAndMatchingSecret() {
        ReflectionTestUtils.setField(controller, "adminRechargeToken", " recharge-secret ");
        assertThrows(
                ResponseStatusException.class,
                () -> controller.recharge(Map.of("amount", "10"), "recharge-secret"));

        user.setAdmin(true);
        ReflectionTestUtils.setField(controller, "adminRechargeToken", " ");
        assertThrows(
                ResponseStatusException.class,
                () -> controller.recharge(Map.of("amount", "10"), "recharge-secret"));

        ReflectionTestUtils.setField(controller, "adminRechargeToken", "recharge-secret");
        assertThrows(
                ResponseStatusException.class,
                () -> controller.recharge(Map.of("amount", "10", "recharge_token", "bad"), null));
        assertFalse((Boolean) controller.recharge(
                        Map.of("amount", "0", "recharge_token", "recharge-secret"), null)
                .get("ok"));
        assertTrue((Boolean) controller.recharge(
                        Map.of(
                                "amount", "10.00",
                                "recharge_token", "recharge-secret",
                                "description", "manual"),
                        " ")
                .get("ok"));
        verify(walletService).addBalance(user, new BigDecimal("10.00"), "manual_recharge", "manual");

        doThrow(new IllegalStateException("db"))
                .when(walletService)
                .addBalance(user, new BigDecimal("11.00"), "manual_recharge", "后台钱包充值");
        assertFalse((Boolean) controller.recharge(
                        Map.of("amount", "11.00", "recharge_token", "recharge-secret"), null)
                .get("ok"));
    }

    @Test
    void selfCreditValidatesAdminCapAmountAndDescription() {
        assertThrows(ResponseStatusException.class, () -> controller.adminSelfCredit(Map.of("amount", "1")));
        user.setAdmin(true);

        ReflectionTestUtils.setField(controller, "adminSelfCreditCapRaw", "invalid");
        assertTrue((Boolean) controller.adminSelfCredit(Map.of("amount", "1", "description", " ")).get("ok"));
        verify(walletService)
                .addBalance(user, new BigDecimal("1.00"), "admin_self_credit", "管理员本人加款");

        ReflectionTestUtils.setField(controller, "adminSelfCreditCapRaw", "0");
        assertFalse((Boolean) controller.adminSelfCredit(Map.of("amount", "0")).get("ok"));

        ReflectionTestUtils.setField(controller, "adminSelfCreditCapRaw", "10");
        assertThrows(
                ResponseStatusException.class,
                () -> controller.adminSelfCredit(Map.of("amount", "11")));

        doThrow(new IllegalStateException("db"))
                .when(walletService)
                .addBalance(user, new BigDecimal("2.00"), "admin_self_credit", "credit");
        assertFalse((Boolean) controller.adminSelfCredit(
                        Map.of("amount", "2", "description", "credit"))
                .get("ok"));
    }

    @Test
    void aiHoldLifecycleMapsSuccessAndServiceFailures() {
        WalletHold hold = hold();
        when(walletService.preauthorizeAiUsage(
                        eq(user), eq(new BigDecimal("5.00")), eq("openai"), eq("gpt"), eq("req"), eq("idem")))
                .thenReturn(hold);
        assertTrue((Boolean) controller.preauthorizeAiUsage(Map.of(
                        "amount", "5.00",
                        "provider", "openai",
                        "model", "gpt",
                        "request_id", "req",
                        "idempotency_key", "idem"))
                .get("ok"));

        when(walletService.settleAiUsage(user, "H-1", new BigDecimal("4.00"), "settle"))
                .thenReturn(hold);
        assertTrue((Boolean) controller.settleAiUsage(Map.of(
                        "hold_no", "H-1", "actual_amount", "4.00", "idempotency_key", "settle"))
                .get("ok"));

        when(walletService.releaseAiUsage(user, "H-1", "unused", "release"))
                .thenReturn(hold);
        assertTrue((Boolean) controller.releaseAiUsage(Map.of(
                        "hold_no", "H-1", "reason", "unused", "idempotency_key", "release"))
                .get("ok"));

        when(walletService.preauthorizeAiUsage(any(), any(), anyString(), anyString(), anyString(), anyString()))
                .thenThrow(new IllegalArgumentException("insufficient balance"));
        assertEquals("insufficient balance", controller.preauthorizeAiUsage(Map.of("amount", "9")).get("message"));
        when(walletService.settleAiUsage(any(), anyString(), any(), anyString()))
                .thenThrow(new IllegalArgumentException("missing hold"));
        assertFalse((Boolean) controller.settleAiUsage(Map.of("actual_amount", "1")).get("ok"));
        when(walletService.releaseAiUsage(any(), anyString(), anyString(), anyString()))
                .thenThrow(new IllegalArgumentException("already released"));
        assertFalse((Boolean) controller.releaseAiUsage(Map.of()).get("ok"));
    }

    @Test
    void transactionsAndOverviewExposeAuditableMoneyHistory() {
        Transaction transaction = transaction();
        Order order = order();
        Refund refund = refund(order);
        Wallet wallet = new Wallet();
        wallet.setBalance(new BigDecimal("88.00"));
        wallet.setUpdatedAt(LocalDateTime.now());
        when(walletService.getWallet(user)).thenReturn(Optional.of(wallet));
        when(walletService.getTransactions(user, 20, 2)).thenReturn(List.of(transaction));
        when(walletService.countTransactions(user)).thenReturn(1L);
        when(orderService.findByUser(user, null, 20, 2)).thenReturn(List.of(order));
        when(orderService.countByUser(user, null)).thenReturn(1L);
        when(refundService.findByUser(user, 20, 2)).thenReturn(List.of(refund));
        when(refundService.countByUser(user)).thenReturn(1L);

        assertEquals(1L, controller.getTransactions(20, 2).get("total"));
        Map<String, Object> overview = controller.overview(20, 2);
        assertEquals(1L, overview.get("transaction_total"));
        assertEquals(1, ((List<?>) overview.get("orders")).size());
        assertEquals(1, ((List<?>) overview.get("refunds")).size());

        when(walletService.getTransactions(user, 20, 2)).thenThrow(new IllegalStateException("db"));
        assertFalse((Boolean) controller.getTransactions(20, 2).get("ok"));
        assertFalse((Boolean) controller.overview(20, 2).get("ok"));
    }

    private static WalletHold hold() {
        WalletHold hold = new WalletHold();
        hold.setId(1L);
        hold.setHoldNo("H-1");
        hold.setAmount(new BigDecimal("5.00"));
        hold.setSettledAmount(new BigDecimal("4.00"));
        hold.setStatus("settled");
        hold.setProvider("openai");
        hold.setModel("gpt");
        hold.setRequestId("req");
        hold.setPreauthTransactionId(2L);
        hold.setSettlementTransactionId(3L);
        hold.setCreatedAt(LocalDateTime.now());
        hold.setExpiresAt(LocalDateTime.now().plusMinutes(5));
        hold.setSettledAt(LocalDateTime.now());
        hold.setReleasedAt(LocalDateTime.now());
        return hold;
    }

    private static Transaction transaction() {
        Transaction transaction = new Transaction();
        transaction.setId(1L);
        transaction.setAmount(BigDecimal.ONE);
        transaction.setTransactionType("credit");
        transaction.setStatus("success");
        transaction.setDescription("grant");
        transaction.setReferenceNo("REF-1");
        transaction.setOrderNo("OT-1");
        transaction.setRefundNo("RF-1");
        transaction.setBalanceBefore(BigDecimal.ZERO);
        transaction.setBalanceAfter(BigDecimal.ONE);
        transaction.setCreatedAt(LocalDateTime.now());
        return transaction;
    }

    private static Order order() {
        Order order = new Order();
        order.setOutTradeNo("OT-1");
        order.setUser(new User());
        order.setStatus("paid");
        order.setSubject("VIP");
        order.setTotalAmount(new BigDecimal("99.00"));
        order.setOrderKind("plan");
        order.setCreatedAt(LocalDateTime.now());
        return order;
    }

    private static Refund refund(Order order) {
        Refund refund = new Refund();
        refund.setId(1L);
        refund.setRefundNo("RF-1");
        refund.setOrder(order);
        refund.setAmount(BigDecimal.ONE);
        refund.setReason("duplicate");
        refund.setStatus("approved");
        refund.setWalletTransactionId(9L);
        refund.setCreatedAt(LocalDateTime.now());
        refund.setReviewedAt(LocalDateTime.now());
        return refund;
    }
}
