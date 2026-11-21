package com.modstore.controller;

import com.modstore.model.Order;
import com.modstore.model.Refund;
import com.modstore.model.Transaction;
import com.modstore.model.User;
import com.modstore.model.Wallet;
import com.modstore.repository.*;
import com.modstore.service.*;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.web.server.ResponseStatusException;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.atomic.AtomicReference;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

class InternalRefundEvidenceControllerTest {
    private RefundRepository refunds;
    private TransactionRepository transactions;
    private InternalRefundEvidenceController controller;
    private InternalPaymentController authentication;
    private Refund refund;
    private Transaction credit;
    private Order order;
    private Wallet wallet;

    @BeforeEach
    void produceNativeWalletRefund() {
        refunds = mock(RefundRepository.class);
        transactions = mock(TransactionRepository.class);
        OrderRepository orders = mock(OrderRepository.class);
        WalletRepository wallets = mock(WalletRepository.class);
        AccountLevelService levels = mock(AccountLevelService.class);
        WalletService money = new WalletService(wallets, transactions,
                mock(WalletHoldRepository.class), mock(UserPlanRepository.class), levels);
        RefundService service = new RefundService(refunds, orders, money,
                mock(EntitlementService.class), levels, mock(AssetInstallCommandService.class));
        User user = new User();
        user.setId(7L);
        User admin = new User();
        admin.setId(8L);
        admin.setAdmin(true);
        order = new Order();
        order.setId(10L);
        order.setOutTradeNo("customer-order-10");
        order.setUser(user);
        order.setSubject("Purchased file service");
        order.setTotalAmount(new BigDecimal("29.90"));
        order.setOrderKind("item");
        order.setStatus("paid");
        order.setFulfilled(true);
        order.setPaidAt(LocalDateTime.now().minusDays(1));
        order.setPayType("page");
        order.setTradeNo("alipay-trade-10");
        wallet = new Wallet();
        wallet.setUser(user);
        wallet.setBalance(new BigDecimal("10.00"));
        when(wallets.findByUserIdForUpdate(7L)).thenReturn(Optional.of(wallet));
        when(wallets.save(any(Wallet.class))).thenAnswer(call -> call.getArgument(0));
        when(orders.findByOutTradeNoForUpdate(order.getOutTradeNo())).thenReturn(Optional.of(order));
        when(orders.save(any(Order.class))).thenAnswer(call -> call.getArgument(0));
        when(refunds.save(any(Refund.class))).thenAnswer(call -> {
            Refund result = call.getArgument(0);
            result.setId(11L);
            return result;
        });
        AtomicReference<Transaction> written = new AtomicReference<>();
        when(transactions.save(any(Transaction.class))).thenAnswer(call -> {
            Transaction result = call.getArgument(0);
            result.setId(21L);
            result.setCreatedAt(LocalDateTime.now()); // JPA's original @PrePersist.
            written.set(result);
            return result;
        });
        refund = service.apply(user, order.getOutTradeNo(), "Original paid service refund");
        when(refunds.findByIdForUpdate(11L)).thenReturn(Optional.of(refund));
        service.review(admin, 11L, "approve", "Original approval");
        credit = written.get();
        when(transactions.findById(21L)).thenReturn(Optional.of(credit));
        when(refunds.evidenceThroughId(any(), any())).thenReturn(11L);
        when(refunds.evidenceCount(any(), any(), eq(11L))).thenReturn(1L);
        when(refunds.evidencePage(any(), any(), eq(0L), eq(11L), any())).thenReturn(List.of(refund));
        authentication = new InternalPaymentController(mock(UserRepository.class),
                mock(OrderService.class), mock(AlipayService.class), mock(WechatPayService.class),
                money, wallets, transactions);
        ReflectionTestUtils.setField(authentication, "internalApiKey", "source-key");
        controller = new InternalRefundEvidenceController(authentication, refunds, transactions);
        ReflectionTestUtils.setField(controller, "deployTier", "production");
    }

    @SuppressWarnings("unchecked")
    private Map<String, Object> proof() {
        Map<String, Object> page = controller.evidence("source-key", 90, 1000, 0, 0, "");
        assertThat(page.get("total")).isEqualTo(1L);
        assertThat(page.get("next_after")).isNull();
        return ((List<Map<String, Object>>) page.get("refunds")).get(0);
    }

    @Test
    void originalReviewAndWalletCreditSupplyTheReadOnlyEvidence() {
        Map<String, Object> row = proof();
        assertThat(wallet.getBalance()).isEqualByComparingTo("39.90");
        assertThat(refund.getStatus()).isEqualTo("approved");
        assertThat(row).containsEntry("verified", true).containsEntry("amount_cents", 2990L)
                .containsEntry("currency", "CNY").containsEntry("wallet_transaction_id", credit.getId())
                .containsEntry("order_no", order.getOutTradeNo()).containsEntry("user_id", 7L)
                .containsEntry("refund_no", refund.getRefundNo())
                .containsEntry("verification", "java_wallet_credit_confirmed");
        assertThat(row).doesNotContainKeys("balance_before", "balance_after", "reason", "admin_note");
        proof();
        verify(transactions, times(1)).save(any(Transaction.class));
        assertThat(wallet.getBalance()).isEqualByComparingTo("39.90");
    }

    @ParameterizedTest
    @ValueSource(strings = {"missing_status", "missing_amount", "missing_transaction", "wrong_user",
            "wrong_order", "wrong_refund", "wrong_amount", "wrong_balance", "pending_transaction",
            "wrong_type", "missing_time", "future_time", "missing_trade", "test_environment"})
    void incompleteOrUnrelatedLedgerFactsRemainUnknown(String fault) {
        switch (fault) {
            case "missing_status" -> order.setStatus(null);
            case "missing_amount" -> refund.setAmount(null);
            case "missing_transaction" -> when(transactions.findById(21L)).thenReturn(Optional.empty());
            case "wrong_user" -> { User other = new User(); other.setId(99L); credit.setUser(other); }
            case "wrong_order" -> credit.setOrderNo("another-order");
            case "wrong_refund" -> credit.setRefundNo("another-refund");
            case "wrong_amount" -> credit.setAmount(new BigDecimal("28.90"));
            case "wrong_balance" -> credit.setBalanceAfter(new BigDecimal("100.00"));
            case "pending_transaction" -> credit.setStatus("pending");
            case "wrong_type" -> credit.setTransactionType("admin_credit");
            case "missing_time" -> refund.setReviewedAt(null);
            case "future_time" -> refund.setReviewedAt(LocalDateTime.now().plusDays(1));
            case "missing_trade" -> order.setTradeNo(null);
            case "test_environment" -> ReflectionTestUtils.setField(controller, "deployTier", "sandbox");
            default -> throw new AssertionError(fault);
        }
        assertThat(proof()).containsEntry("verified", false)
                .doesNotContainKeys("amount_cents", "currency", "order_no", "user_id");
    }

    @Test
    void originalInternalAuthenticationAndPinnedCursorAreRequired() {
        assertThatThrownBy(() -> controller.evidence("wrong", 90, 1000, 0, 0, ""))
                .isInstanceOf(ResponseStatusException.class);
        assertThatThrownBy(() -> controller.evidence("source-key", 90, 1000, 11, 11, ""))
                .isInstanceOf(ResponseStatusException.class);
        ReflectionTestUtils.setField(authentication, "internalApiKey", "");
        assertThatThrownBy(() -> controller.evidence("", 90, 1000, 0, 0, ""))
                .isInstanceOf(ResponseStatusException.class);
        verify(refunds, never()).evidencePage(any(), any(), anyLong(), anyLong(), any());
    }
}
