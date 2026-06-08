package com.modstore.service;

import com.modstore.model.*;
import com.modstore.repository.*;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.*;
import org.mockito.junit.jupiter.MockitoExtension;

import java.math.BigDecimal;
import java.util.List;
import java.util.Optional;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

@ExtendWith(MockitoExtension.class)
class WalletServiceTest {

    @Mock WalletRepository walletRepository;
    @Mock TransactionRepository transactionRepository;
    @Mock WalletHoldRepository walletHoldRepository;
    @Mock UserPlanRepository userPlanRepository;
    @Mock AccountLevelService accountLevelService;

    @InjectMocks WalletService walletService;

    private User user;
    private Wallet wallet;

    @BeforeEach
    void setUp() {
        user = new User();
        user.setId(1L);
        user.setUsername("testuser");
        user.setPasswordHash("hash");

        wallet = new Wallet();
        wallet.setId(1L);
        wallet.setUser(user);
        wallet.setBalance(BigDecimal.ZERO);
    }

    private void stubWalletFindByUser() {
        when(walletRepository.findByUser(user)).thenReturn(Optional.of(wallet));
    }

    private void stubWalletFindByUserIdForUpdate() {
        when(walletRepository.findByUserIdForUpdate(user.getId())).thenReturn(Optional.of(wallet));
    }

    private void stubSaveWallet() {
        when(walletRepository.save(any(Wallet.class))).thenAnswer(inv -> inv.getArgument(0));
    }

    private void stubSaveTransaction() {
        when(transactionRepository.save(any(Transaction.class))).thenAnswer(inv -> {
            Transaction t = inv.getArgument(0);
            t.setId(System.nanoTime());
            return t;
        });
    }

    @Nested
    class GetOrCreateWallet {
        @Test
        void returnsExistingWallet() {
            stubWalletFindByUser();
            Wallet result = walletService.getOrCreateWallet(user);
            assertThat(result).isSameAs(wallet);
        }

        @Test
        void createsNewWalletWhenNone() {
            when(walletRepository.findByUser(user)).thenReturn(Optional.empty());
            when(walletRepository.save(any(Wallet.class))).thenAnswer(inv -> inv.getArgument(0));

            Wallet result = walletService.getOrCreateWallet(user);
            assertThat(result.getUser()).isEqualTo(user);
            assertThat(result.getBalance()).isEqualByComparingTo(BigDecimal.ZERO);
        }
    }

    @Nested
    class CreditAndDebit {
        @Test
        void creditIncreasesBalance() {
            stubWalletFindByUserIdForUpdate();
            stubSaveWallet();
            stubSaveTransaction();

            Transaction txn = walletService.credit(user, new BigDecimal("50.00"), "test_credit",
                    "test", "ref-1", "order-1", null, "idem-1");

            assertThat(wallet.getBalance()).isEqualByComparingTo(new BigDecimal("50.00"));
            assertThat(txn.getAmount()).isEqualByComparingTo(new BigDecimal("50.00"));
        }

        @Test
        void debitDecreasesBalance() {
            wallet.setBalance(new BigDecimal("100.00"));
            stubWalletFindByUserIdForUpdate();
            stubSaveWallet();
            stubSaveTransaction();

            walletService.debit(user, new BigDecimal("30.00"), "test_debit", "test", null, null, null, null);

            assertThat(wallet.getBalance()).isEqualByComparingTo(new BigDecimal("70.00"));
        }

        @Test
        void debitInsufficientBalanceThrows() {
            wallet.setBalance(new BigDecimal("10.00"));
            stubWalletFindByUserIdForUpdate();
            stubSaveWallet();

            assertThatThrownBy(() -> walletService.debit(user, new BigDecimal("50.00"), "test", "test",
                    null, null, null, null))
                    .isInstanceOf(IllegalArgumentException.class)
                    .hasMessageContaining("余额不足");
        }

        @Test
        void zeroAmountThrows() {
            assertThatThrownBy(() -> walletService.credit(user, BigDecimal.ZERO, "test", "test",
                    null, null, null, null))
                    .isInstanceOf(IllegalArgumentException.class)
                    .hasMessageContaining("大于 0");
        }

        @Test
        void negativeAmountThrows() {
            assertThatThrownBy(() -> walletService.credit(user, new BigDecimal("-5"), "test", "test",
                    null, null, null, null))
                    .isInstanceOf(IllegalArgumentException.class)
                    .hasMessageContaining("大于 0");
        }

        @Test
        void nullAmountThrows() {
            assertThatThrownBy(() -> walletService.credit(user, null, "test", "test",
                    null, null, null, null))
                    .isInstanceOf(IllegalArgumentException.class);
        }
    }

    @Nested
    class Idempotency {
        @Test
        void duplicateIdempotencyKeyReturnsExistingTransaction() {
            Transaction existing = new Transaction();
            existing.setId(42L);
            existing.setIdempotencyKey("idem-dup");
            when(transactionRepository.findByIdempotencyKey("idem-dup")).thenReturn(Optional.of(existing));
            stubWalletFindByUserIdForUpdate();

            Transaction result = walletService.credit(user, new BigDecimal("10.00"), "test", "test",
                    null, null, null, "idem-dup");

            assertThat(result).isSameAs(existing);
            verify(walletRepository, never()).save(any());
        }

        @Test
        void nullIdempotencyKeyAlwaysCreatesNew() {
            stubWalletFindByUserIdForUpdate();
            stubSaveWallet();
            stubSaveTransaction();

            walletService.credit(user, new BigDecimal("10.00"), "test", "test",
                    null, null, null, null);

            verify(transactionRepository).save(any(Transaction.class));
        }
    }

    @Nested
    class GrantPlanMembershipTokenAllowance {
        @Test
        void grantsTokensForPlanOrder() {
            Order order = new Order();
            order.setUser(user);
            order.setTotalAmount(new BigDecimal("199.00"));
            order.setOrderKind("plan");
            order.setOutTradeNo("OT-G1");
            stubWalletFindByUserIdForUpdate();
            stubSaveWallet();
            stubSaveTransaction();

            walletService.grantPlanMembershipTokenAllowance(order);

            verify(transactionRepository).save(argThat(t ->
                    "plan_membership_tokens".equals(t.getTransactionType())));
        }

        @Test
        void noopsForNonPlanOrder() {
            Order order = new Order();
            order.setOrderKind("item");

            walletService.grantPlanMembershipTokenAllowance(order);

            verifyNoInteractions(walletRepository);
            verifyNoInteractions(transactionRepository);
        }

        @Test
        void noopsForNullOrder() {
            walletService.grantPlanMembershipTokenAllowance(null);
            verifyNoInteractions(walletRepository);
        }

        @Test
        void noopsForZeroAmountPlan() {
            Order order = new Order();
            order.setUser(user);
            order.setTotalAmount(new BigDecimal("0.49"));
            order.setOrderKind("plan");

            walletService.grantPlanMembershipTokenAllowance(order);

            verifyNoInteractions(transactionRepository);
        }
    }

    @Nested
    class RevokePlanMembershipTokenAllowance {
        @Test
        void revokesTokensWhenBalanceSufficient() {
            Order order = new Order();
            order.setUser(user);
            order.setTotalAmount(new BigDecimal("199.00"));
            order.setOrderKind("plan");
            order.setOutTradeNo("OT-R1");

            wallet.setBalance(new BigDecimal("199.00"));
            stubWalletFindByUser();
            stubWalletFindByUserIdForUpdate();
            stubSaveWallet();
            stubSaveTransaction();

            walletService.revokePlanMembershipTokenAllowance(order);

            verify(transactionRepository).save(argThat(t ->
                    "plan_membership_tokens_revoke".equals(t.getTransactionType())));
        }

        @Test
        void takesMinWhenBalanceLessThanGrant() {
            Order order = new Order();
            order.setUser(user);
            order.setTotalAmount(new BigDecimal("199.00"));
            order.setOrderKind("plan");
            order.setOutTradeNo("OT-R2");

            wallet.setBalance(new BigDecimal("50.00"));
            stubWalletFindByUser();
            stubWalletFindByUserIdForUpdate();
            stubSaveWallet();
            stubSaveTransaction();

            walletService.revokePlanMembershipTokenAllowance(order);

            verify(transactionRepository).save(argThat(t ->
                    t.getAmount().compareTo(new BigDecimal("-50.00")) == 0));
        }

        @Test
        void noopsWhenBalanceIsZero() {
            Order order = new Order();
            order.setUser(user);
            order.setTotalAmount(new BigDecimal("199.00"));
            order.setOrderKind("plan");
            order.setOutTradeNo("OT-R3");

            wallet.setBalance(BigDecimal.ZERO);
            stubWalletFindByUser();

            walletService.revokePlanMembershipTokenAllowance(order);

            verify(transactionRepository, never()).save(any());
        }
    }

    @Nested
    class AiUsagePreauth {
        @Test
        void preauthorizeCreatesHoldAndDebits() {
            wallet.setBalance(new BigDecimal("100.00"));
            stubWalletFindByUserIdForUpdate();
            stubSaveWallet();
            stubSaveTransaction();
            when(walletHoldRepository.findByIdempotencyKey("idem-ai-1")).thenReturn(Optional.empty());
            when(walletHoldRepository.save(any(WalletHold.class))).thenAnswer(inv -> inv.getArgument(0));

            WalletHold hold = walletService.preauthorizeAiUsage(user, new BigDecimal("5.00"),
                    "openai", "gpt-4", "req-1", "idem-ai-1");

            assertThat(hold.getStatus()).isEqualTo("held");
            assertThat(hold.getAmount()).isEqualByComparingTo(new BigDecimal("5.00"));
            verify(transactionRepository).save(argThat(t -> "ai_preauth".equals(t.getTransactionType())));
        }

        @Test
        void preauthorizeIdempotencyReturnsExisting() {
            WalletHold existing = new WalletHold();
            existing.setIdempotencyKey("idem-ai-2");
            when(walletHoldRepository.findByIdempotencyKey("idem-ai-2")).thenReturn(Optional.of(existing));

            WalletHold result = walletService.preauthorizeAiUsage(user, new BigDecimal("5.00"),
                    "openai", "gpt-4", "req-2", "idem-ai-2");

            assertThat(result).isSameAs(existing);
            verify(transactionRepository, never()).save(any());
        }

        @Test
        void preauthorizeRequiresIdempotencyKey() {
            assertThatThrownBy(() -> walletService.preauthorizeAiUsage(user, new BigDecimal("5.00"),
                    "openai", "gpt-4", "req-3", null))
                    .isInstanceOf(IllegalArgumentException.class)
                    .hasMessageContaining("idempotency_key");
        }

        @Test
        void settleExactAmountNoExtraTransaction() {
            WalletHold hold = new WalletHold();
            hold.setHoldNo("AIH1");
            hold.setUser(user);
            hold.setAmount(new BigDecimal("5.00"));
            hold.setStatus("held");
            hold.setProvider("openai");
            hold.setModel("gpt-4");
            hold.setRequestId("req-1");

            when(walletHoldRepository.findByHoldNo("AIH1")).thenReturn(Optional.of(hold));
            when(walletHoldRepository.save(any(WalletHold.class))).thenAnswer(inv -> inv.getArgument(0));

            WalletHold settled = walletService.settleAiUsage(user, "AIH1", new BigDecimal("5.00"), "idem-settle-1");

            assertThat(settled.getStatus()).isEqualTo("settled");
            assertThat(settled.getSettledAmount()).isEqualByComparingTo(new BigDecimal("5.00"));
        }

        @Test
        void settleExtraAmountDebitsDelta() {
            wallet.setBalance(new BigDecimal("100.00"));
            WalletHold hold = new WalletHold();
            hold.setHoldNo("AIH2");
            hold.setUser(user);
            hold.setAmount(new BigDecimal("5.00"));
            hold.setStatus("held");
            hold.setProvider("openai");
            hold.setModel("gpt-4");
            hold.setRequestId("req-2");

            when(walletHoldRepository.findByHoldNo("AIH2")).thenReturn(Optional.of(hold));
            when(walletHoldRepository.save(any(WalletHold.class))).thenAnswer(inv -> inv.getArgument(0));
            stubWalletFindByUserIdForUpdate();
            stubSaveWallet();
            stubSaveTransaction();

            WalletHold settled = walletService.settleAiUsage(user, "AIH2", new BigDecimal("7.00"), "idem-settle-2");

            assertThat(settled.getStatus()).isEqualTo("settled");
            verify(transactionRepository).save(argThat(t ->
                    "ai_settle_extra".equals(t.getTransactionType())));
        }

        @Test
        void settleLessAmountCreditsBack() {
            WalletHold hold = new WalletHold();
            hold.setHoldNo("AIH3");
            hold.setUser(user);
            hold.setAmount(new BigDecimal("5.00"));
            hold.setStatus("held");
            hold.setProvider("openai");
            hold.setModel("gpt-4");
            hold.setRequestId("req-3");

            when(walletHoldRepository.findByHoldNo("AIH3")).thenReturn(Optional.of(hold));
            when(walletHoldRepository.save(any(WalletHold.class))).thenAnswer(inv -> inv.getArgument(0));
            stubWalletFindByUserIdForUpdate();
            stubSaveWallet();
            stubSaveTransaction();

            WalletHold settled = walletService.settleAiUsage(user, "AIH3", new BigDecimal("3.00"), "idem-settle-3");

            assertThat(settled.getStatus()).isEqualTo("settled");
            verify(transactionRepository).save(argThat(t ->
                    "ai_release".equals(t.getTransactionType())));
        }

        @Test
        void settleReleasedHoldThrows() {
            WalletHold hold = new WalletHold();
            hold.setHoldNo("AIH4");
            hold.setUser(user);
            hold.setAmount(new BigDecimal("5.00"));
            hold.setStatus("released");

            when(walletHoldRepository.findByHoldNo("AIH4")).thenReturn(Optional.of(hold));

            assertThatThrownBy(() -> walletService.settleAiUsage(user, "AIH4", new BigDecimal("5.00"), "idem-4"))
                    .isInstanceOf(IllegalStateException.class)
                    .hasMessageContaining("已释放");
        }

        @Test
        void releaseCreditsBackFullAmount() {
            WalletHold hold = new WalletHold();
            hold.setHoldNo("AIH5");
            hold.setUser(user);
            hold.setAmount(new BigDecimal("5.00"));
            hold.setStatus("held");
            hold.setRequestId("req-5");

            when(walletHoldRepository.findByHoldNo("AIH5")).thenReturn(Optional.of(hold));
            when(walletHoldRepository.save(any(WalletHold.class))).thenAnswer(inv -> inv.getArgument(0));
            stubWalletFindByUserIdForUpdate();
            stubSaveWallet();
            stubSaveTransaction();

            WalletHold released = walletService.releaseAiUsage(user, "AIH5", "timeout", "idem-release-1");

            assertThat(released.getStatus()).isEqualTo("released");
            verify(transactionRepository).save(argThat(t ->
                    "ai_release".equals(t.getTransactionType())));
        }

        @Test
        void releaseAlreadySettledIsNoop() {
            WalletHold hold = new WalletHold();
            hold.setHoldNo("AIH6");
            hold.setUser(user);
            hold.setAmount(new BigDecimal("5.00"));
            hold.setStatus("settled");

            when(walletHoldRepository.findByHoldNo("AIH6")).thenReturn(Optional.of(hold));

            WalletHold result = walletService.releaseAiUsage(user, "AIH6", "test", "idem-6");

            assertThat(result.getStatus()).isEqualTo("settled");
            verify(transactionRepository, never()).save(any());
        }
    }

    @Nested
    class RecordExternalPaymentAndSpend {
        @Test
        void recordExternalPaymentCreditsWallet() {
            Order order = new Order();
            order.setUser(user);
            order.setTotalAmount(new BigDecimal("99.00"));
            order.setSubject("Test Plan");
            order.setOutTradeNo("OT-EP1");
            stubWalletFindByUserIdForUpdate();
            stubSaveWallet();
            stubSaveTransaction();

            Transaction txn = walletService.recordExternalPayment(order);

            assertThat(txn.getTransactionType()).isEqualTo("alipay_payment");
        }

        @Test
        void recordOrderSpendDebitsWallet() {
            Order order = new Order();
            order.setUser(user);
            order.setTotalAmount(new BigDecimal("99.00"));
            order.setSubject("Test Plan");
            order.setOutTradeNo("OT-OS1");
            order.setOrderKind("plan");
            wallet.setBalance(new BigDecimal("99.00"));
            stubWalletFindByUserIdForUpdate();
            stubSaveWallet();
            stubSaveTransaction();

            Transaction txn = walletService.recordOrderSpend(order);

            assertThat(txn.getTransactionType()).isEqualTo("plan_purchase");
        }

        @Test
        void recordOrderSpendItemKind() {
            Order order = new Order();
            order.setUser(user);
            order.setTotalAmount(new BigDecimal("29.90"));
            order.setSubject("Test Item");
            order.setOutTradeNo("OT-OS2");
            order.setOrderKind("item");
            wallet.setBalance(new BigDecimal("29.90"));
            stubWalletFindByUserIdForUpdate();
            stubSaveWallet();
            stubSaveTransaction();

            Transaction txn = walletService.recordOrderSpend(order);

            assertThat(txn.getTransactionType()).isEqualTo("item_purchase");
        }
    }

    @Nested
    class RefundToWallet {
        @Test
        void refundCreditsWallet() {
            Order order = new Order();
            order.setUser(user);
            order.setTotalAmount(new BigDecimal("99.00"));
            order.setSubject("Refund Test");
            order.setOutTradeNo("OT-RF1");

            Refund refund = new Refund();
            refund.setUser(user);
            refund.setAmount(new BigDecimal("99.00"));
            refund.setRefundNo("RF1");

            stubWalletFindByUserIdForUpdate();
            stubSaveWallet();
            stubSaveTransaction();

            Transaction txn = walletService.refundToWallet(order, refund);

            assertThat(txn.getTransactionType()).isEqualTo("wallet_refund");
            assertThat(txn.getRefundNo()).isEqualTo("RF1");
        }
    }

    @Nested
    class MembershipReferenceLine {
        @Test
        void returnsZeroWhenNoData() {
            stubWalletFindByUser();
            when(transactionRepository.sumMembershipReferenceNet(user)).thenReturn(null);
            when(userPlanRepository.findFirstByUserAndActiveTrueOrderByStartedAtDesc(user))
                    .thenReturn(Optional.empty());

            int line = walletService.getMembershipReferenceLineYuan(user);

            assertThat(line).isEqualTo(0);
        }

        @Test
        void returnsNetFromTransactions() {
            stubWalletFindByUser();
            when(transactionRepository.sumMembershipReferenceNet(user)).thenReturn(new BigDecimal("199"));

            int line = walletService.getMembershipReferenceLineYuan(user);

            assertThat(line).isEqualTo(199);
        }

        @Test
        void fallsBackToPlanPriceWhenNetIsZero() {
            stubWalletFindByUser();
            when(transactionRepository.sumMembershipReferenceNet(user)).thenReturn(BigDecimal.ZERO);

            PlanTemplate plan = new PlanTemplate();
            plan.setPrice(new BigDecimal("99.00"));
            UserPlan userPlan = new UserPlan();
            userPlan.setPlan(plan);
            when(userPlanRepository.findFirstByUserAndActiveTrueOrderByStartedAtDesc(user))
                    .thenReturn(Optional.of(userPlan));

            int line = walletService.getMembershipReferenceLineYuan(user);

            assertThat(line).isEqualTo(99);
        }
    }
}
