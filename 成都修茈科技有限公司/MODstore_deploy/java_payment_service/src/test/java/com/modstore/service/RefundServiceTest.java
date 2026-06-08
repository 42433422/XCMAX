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
import java.util.Optional;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

@ExtendWith(MockitoExtension.class)
class RefundServiceTest {

    @Mock RefundRepository refundRepository;
    @Mock OrderRepository orderRepository;
    @Mock WalletService walletService;
    @Mock EntitlementService entitlementService;
    @Mock AccountLevelService accountLevelService;

    @InjectMocks RefundService refundService;

    private User user;
    private User admin;

    @BeforeEach
    void setUp() {
        user = new User();
        user.setId(1L);
        user.setUsername("testuser");
        user.setPasswordHash("hash");

        admin = new User();
        admin.setId(2L);
        admin.setUsername("admin");
        admin.setPasswordHash("hash");
        admin.setAdmin(true);
    }

    private Order buildFulfilledPaidOrder(String outTradeNo, String kind, BigDecimal amount) {
        Order order = new Order();
        order.setOutTradeNo(outTradeNo);
        order.setUser(user);
        order.setSubject("test");
        order.setTotalAmount(amount);
        order.setOrderKind(kind);
        order.setStatus("paid");
        order.setFulfilled(true);
        order.setRefundedAmount(BigDecimal.ZERO);
        return order;
    }

    @Nested
    class Apply {
        @Test
        void createsRefundForFulfilledPaidOrder() {
            Order order = buildFulfilledPaidOrder("OT-RF1", "item", new BigDecimal("29.90"));
            when(orderRepository.findByOutTradeNoForUpdate("OT-RF1")).thenReturn(Optional.of(order));
            when(refundRepository.findFirstByOrderAndStatusIn(eq(order), anyList())).thenReturn(Optional.empty());
            when(refundRepository.save(any(Refund.class))).thenAnswer(inv -> inv.getArgument(0));
            when(orderRepository.save(any(Order.class))).thenAnswer(inv -> inv.getArgument(0));

            Refund refund = refundService.apply(user, "OT-RF1", "商品与描述不符，申请退款处理");

            assertThat(refund.getStatus()).isEqualTo("pending");
            assertThat(refund.getAmount()).isEqualByComparingTo(new BigDecimal("29.90"));
            verify(orderRepository).save(argThat(o -> "refunding".equals(o.getStatus())));
        }

        @Test
        void rejectsEmptyOrderNo() {
            assertThatThrownBy(() -> refundService.apply(user, "", "some reason"))
                    .isInstanceOf(IllegalArgumentException.class)
                    .hasMessageContaining("订单号");
        }

        @Test
        void rejectsShortReason() {
            assertThatThrownBy(() -> refundService.apply(user, "OT-1", "短"))
                    .isInstanceOf(IllegalArgumentException.class)
                    .hasMessageContaining("5-1000");
        }

        @Test
        void rejectsNonOwnerOrder() {
            User other = new User();
            other.setId(999L);
            other.setUsername("other");
            other.setPasswordHash("h");
            Order order = buildFulfilledPaidOrder("OT-RF2", "item", new BigDecimal("29.90"));
            order.setUser(other);
            when(orderRepository.findByOutTradeNoForUpdate("OT-RF2")).thenReturn(Optional.of(order));

            assertThatThrownBy(() -> refundService.apply(user, "OT-RF2", "正当的退款原因描述"))
                    .isInstanceOf(IllegalArgumentException.class)
                    .hasMessageContaining("无权");
        }

        @Test
        void rejectsNonPaidOrder() {
            Order order = buildFulfilledPaidOrder("OT-RF3", "item", new BigDecimal("29.90"));
            order.setStatus("pending");
            when(orderRepository.findByOutTradeNoForUpdate("OT-RF3")).thenReturn(Optional.of(order));

            assertThatThrownBy(() -> refundService.apply(user, "OT-RF3", "正当的退款原因描述"))
                    .isInstanceOf(IllegalArgumentException.class)
                    .hasMessageContaining("已支付");
        }

        @Test
        void rejectsWalletRechargeOrder() {
            Order order = buildFulfilledPaidOrder("OT-RF4", "wallet", new BigDecimal("50.00"));
            when(orderRepository.findByOutTradeNoForUpdate("OT-RF4")).thenReturn(Optional.of(order));

            assertThatThrownBy(() -> refundService.apply(user, "OT-RF4", "正当的退款原因描述"))
                    .isInstanceOf(IllegalArgumentException.class)
                    .hasMessageContaining("钱包充值");
        }

        @Test
        void rejectsAlreadyRefundedOrder() {
            Order order = buildFulfilledPaidOrder("OT-RF5", "item", new BigDecimal("29.90"));
            order.setRefundedAmount(new BigDecimal("29.90"));
            when(orderRepository.findByOutTradeNoForUpdate("OT-RF5")).thenReturn(Optional.of(order));

            assertThatThrownBy(() -> refundService.apply(user, "OT-RF5", "正当的退款原因描述"))
                    .isInstanceOf(IllegalArgumentException.class)
                    .hasMessageContaining("已退款");
        }

        @Test
        void returnsExistingOpenRefund() {
            Order order = buildFulfilledPaidOrder("OT-RF6", "item", new BigDecimal("29.90"));
            when(orderRepository.findByOutTradeNoForUpdate("OT-RF6")).thenReturn(Optional.of(order));

            Refund existing = new Refund();
            existing.setStatus("pending");
            when(refundRepository.findFirstByOrderAndStatusIn(eq(order), anyList())).thenReturn(Optional.of(existing));

            Refund result = refundService.apply(user, "OT-RF6", "正当的退款原因描述");

            assertThat(result).isSameAs(existing);
            verify(refundRepository, never()).save(any());
        }
    }

    @Nested
    class Review {
        @Test
        void approveRefundsToWalletAndRevokesEntitlements() {
            Order order = buildFulfilledPaidOrder("OT-RV1", "item", new BigDecimal("29.90"));
            Refund refund = new Refund();
            refund.setId(10L);
            refund.setOrder(order);
            refund.setUser(user);
            refund.setAmount(new BigDecimal("29.90"));
            refund.setStatus("pending");

            when(refundRepository.findByIdForUpdate(10L)).thenReturn(Optional.of(refund));
            when(orderRepository.findByOutTradeNoForUpdate("OT-RV1")).thenReturn(Optional.of(order));
            when(orderRepository.save(any(Order.class))).thenAnswer(inv -> inv.getArgument(0));

            Transaction walletTxn = new Transaction();
            walletTxn.setId(100L);
            when(walletService.refundToWallet(order, refund)).thenReturn(walletTxn);
            when(refundRepository.save(any(Refund.class))).thenAnswer(inv -> inv.getArgument(0));

            Refund result = refundService.review(admin, 10L, "approve", "审核通过");

            assertThat(result.getStatus()).isEqualTo("approved");
            verify(walletService).refundToWallet(order, refund);
            verify(entitlementService).revokeOrderEntitlements(user, "OT-RV1");
        }

        @Test
        void approvePlanOrderAlsoRevokesTokens() {
            Order order = buildFulfilledPaidOrder("OT-RV2", "plan", new BigDecimal("199.00"));
            Refund refund = new Refund();
            refund.setId(11L);
            refund.setOrder(order);
            refund.setUser(user);
            refund.setAmount(new BigDecimal("199.00"));
            refund.setStatus("pending");

            when(refundRepository.findByIdForUpdate(11L)).thenReturn(Optional.of(refund));
            when(orderRepository.findByOutTradeNoForUpdate("OT-RV2")).thenReturn(Optional.of(order));
            when(orderRepository.save(any(Order.class))).thenAnswer(inv -> inv.getArgument(0));

            Transaction walletTxn = new Transaction();
            walletTxn.setId(101L);
            when(walletService.refundToWallet(order, refund)).thenReturn(walletTxn);
            when(refundRepository.save(any(Refund.class))).thenAnswer(inv -> inv.getArgument(0));

            refundService.review(admin, 11L, "approve", "审核通过");

            verify(walletService).revokePlanMembershipTokenAllowance(order);
        }

        @Test
        void rejectRestoresOrderStatus() {
            Order order = buildFulfilledPaidOrder("OT-RV3", "item", new BigDecimal("29.90"));
            order.setStatus("refunding");
            Refund refund = new Refund();
            refund.setId(12L);
            refund.setOrder(order);
            refund.setUser(user);
            refund.setAmount(new BigDecimal("29.90"));
            refund.setStatus("pending");

            when(refundRepository.findByIdForUpdate(12L)).thenReturn(Optional.of(refund));
            when(orderRepository.findByOutTradeNoForUpdate("OT-RV3")).thenReturn(Optional.of(order));
            when(orderRepository.save(any(Order.class))).thenAnswer(inv -> inv.getArgument(0));
            when(refundRepository.save(any(Refund.class))).thenAnswer(inv -> inv.getArgument(0));

            Refund result = refundService.review(admin, 12L, "reject", "拒绝退款");

            assertThat(result.getStatus()).isEqualTo("rejected");
            verify(walletService, never()).refundToWallet(any(), any());
        }

        @Test
        void nonAdminCannotReview() {
            assertThatThrownBy(() -> refundService.review(user, 10L, "approve", "note"))
                    .isInstanceOf(IllegalArgumentException.class)
                    .hasMessageContaining("管理员");
        }

        @Test
        void invalidActionThrows() {
            Refund refund = new Refund();
            refund.setId(13L);
            refund.setStatus("pending");
            when(refundRepository.findByIdForUpdate(13L)).thenReturn(Optional.of(refund));

            Order order = buildFulfilledPaidOrder("OT-RV4", "item", new BigDecimal("29.90"));
            refund.setOrder(order);
            when(orderRepository.findByOutTradeNoForUpdate(anyString())).thenReturn(Optional.of(order));

            assertThatThrownBy(() -> refundService.review(admin, 13L, "invalid_action", "note"))
                    .isInstanceOf(IllegalArgumentException.class)
                    .hasMessageContaining("无效");
        }

        @Test
        void alreadyReviewedRefundIsIdempotent() {
            Refund refund = new Refund();
            refund.setId(14L);
            refund.setStatus("approved");

            when(refundRepository.findByIdForUpdate(14L)).thenReturn(Optional.of(refund));

            Refund result = refundService.review(admin, 14L, "approve", "再次审核");

            assertThat(result).isSameAs(refund);
            verify(walletService, never()).refundToWallet(any(), any());
        }

        @Test
        void xpRevokeFailureDoesNotBlockRefund() {
            Order order = buildFulfilledPaidOrder("OT-RV5", "item", new BigDecimal("29.90"));
            Refund refund = new Refund();
            refund.setId(15L);
            refund.setOrder(order);
            refund.setUser(user);
            refund.setAmount(new BigDecimal("29.90"));
            refund.setStatus("pending");

            when(refundRepository.findByIdForUpdate(15L)).thenReturn(Optional.of(refund));
            when(orderRepository.findByOutTradeNoForUpdate("OT-RV5")).thenReturn(Optional.of(order));
            when(orderRepository.save(any(Order.class))).thenAnswer(inv -> inv.getArgument(0));

            Transaction walletTxn = new Transaction();
            walletTxn.setId(102L);
            when(walletService.refundToWallet(order, refund)).thenReturn(walletTxn);
            when(refundRepository.save(any(Refund.class))).thenAnswer(inv -> inv.getArgument(0));
            doThrow(new RuntimeException("xp error")).when(accountLevelService).revokeOrderXp(anyLong(), anyString());

            Refund result = refundService.review(admin, 15L, "approve", "审核通过");

            assertThat(result.getStatus()).isEqualTo("approved");
        }
    }
}
