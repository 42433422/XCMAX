package com.modstore.service;

import com.modstore.event.EventContracts;
import com.modstore.model.*;
import com.modstore.repository.*;
import com.modstore.util.MoneyUtils;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.*;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.support.SimpleTransactionStatus;
import org.springframework.transaction.PlatformTransactionManager;

import java.math.BigDecimal;
import java.time.Duration;
import java.time.LocalDateTime;
import java.util.*;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.*;

@ExtendWith(MockitoExtension.class)
class OrderServiceTest {

    @Mock OrderRepository orderRepository;
    @Mock TransactionRepository transactionRepository;
    @Mock WalletService walletService;
    @Mock EntitlementService entitlementService;
    @Mock PlanTemplateRepository planTemplateRepository;
    @Mock CatalogItemRepository catalogItemRepository;
    @Mock WebhookDispatcher webhookDispatcher;
    @Mock AccountLevelService accountLevelService;
    @Mock AlipayService alipayService;
    @Mock WechatPayService wechatPayService;
    @Mock PlatformTransactionManager transactionManager;

    @InjectMocks OrderService orderService;

    private User user;

    @BeforeEach
    void setUp() {
        user = new User();
        user.setId(1L);
        user.setUsername("testuser");
        user.setPasswordHash("hash");
        lenient().when(transactionManager.getTransaction(any(TransactionDefinition.class)))
                .thenReturn(new SimpleTransactionStatus(true));
    }

    private Order buildPendingOrder(String outTradeNo, String kind, BigDecimal amount) {
        Order order = new Order();
        order.setOutTradeNo(outTradeNo);
        order.setUser(user);
        order.setSubject("test");
        order.setTotalAmount(amount);
        order.setOrderKind(kind);
        order.setStatus("pending");
        order.setFulfilled(false);
        return order;
    }

    private Order buildPaidOrder(String outTradeNo, String kind, BigDecimal amount) {
        Order order = buildPendingOrder(outTradeNo, kind, amount);
        order.setStatus("paid");
        order.setPaidAt(LocalDateTime.now());
        return order;
    }

    @Nested
    class CreateOrder {
        @Test
        void createsOrderWithCorrectFields() {
            Order saved = buildPendingOrder("OT-1", "item", new BigDecimal("9.90"));
            when(orderRepository.save(any())).thenAnswer(inv -> inv.getArgument(0));

            Order result = orderService.createOrder(user, "OT-1", "test", new BigDecimal("9.90"),
                    "item", 10L, null, "req-1");

            assertThat(result.getOutTradeNo()).isEqualTo("OT-1");
            assertThat(result.getOrderKind()).isEqualTo("item");
            assertThat(result.getStatus()).isEqualTo("pending");
            assertThat(result.isFulfilled()).isFalse();
            assertThat(result.getRequestId()).isEqualTo("req-1");
        }
    }

    @Nested
    class ResolveCheckoutFields {
        @Test
        void walletRechargeSetsKindAndAmount() {
            Map<String, Object> req = Map.of("wallet_recharge", true, "total_amount", "50.00");

            Map<String, Object> resolved = orderService.resolveCheckoutFields(req, user);

            assertThat(resolved.get("order_kind")).isEqualTo("wallet");
            assertThat(resolved.get("total_amount")).isEqualTo(new BigDecimal("50.00"));
            assertThat(resolved.get("wallet_recharge")).isEqualTo(true);
        }

        @Test
        void walletRechargeRejectsZeroAmount() {
            Map<String, Object> req = Map.of("wallet_recharge", true, "total_amount", "0");

            assertThatThrownBy(() -> orderService.resolveCheckoutFields(req, user))
                    .isInstanceOf(IllegalArgumentException.class)
                    .hasMessageContaining("大于 0");
        }

        @Test
        void planIdResolvesToPlanPrice() {
            PlanTemplate plan = new PlanTemplate();
            plan.setId("pro");
            plan.setPrice(new BigDecimal("199.00"));
            plan.setActive(true);
            when(planTemplateRepository.findById("pro")).thenReturn(Optional.of(plan));

            Map<String, Object> req = Map.of("plan_id", "pro", "wallet_recharge", false);
            Map<String, Object> resolved = orderService.resolveCheckoutFields(req, user);

            assertThat(resolved.get("order_kind")).isEqualTo("plan");
            assertThat(resolved.get("total_amount")).isEqualTo(new BigDecimal("199.00"));
            assertThat(resolved.get("plan_id")).isEqualTo("pro");
        }

        @Test
        void inactivePlanThrows() {
            PlanTemplate plan = new PlanTemplate();
            plan.setId("old");
            plan.setActive(false);
            when(planTemplateRepository.findById("old")).thenReturn(Optional.of(plan));

            Map<String, Object> req = Map.of("plan_id", "old", "wallet_recharge", false);

            assertThatThrownBy(() -> orderService.resolveCheckoutFields(req, user))
                    .isInstanceOf(IllegalArgumentException.class)
                    .hasMessageContaining("套餐不存在");
        }

        @Test
        void itemIdResolvesToItemPrice() {
            CatalogItem item = new CatalogItem();
            item.setId(42L);
            item.setName("Cool MOD");
            item.setPrice(new BigDecimal("29.90"));
            when(catalogItemRepository.findById(42L)).thenReturn(Optional.of(item));
            when(entitlementService.hasPurchasedOrActiveEntitlement(user, 42L)).thenReturn(false);

            Map<String, Object> req = Map.of("item_id", 42, "wallet_recharge", false);
            Map<String, Object> resolved = orderService.resolveCheckoutFields(req, user);

            assertThat(resolved.get("order_kind")).isEqualTo("item");
            assertThat(resolved.get("total_amount")).isEqualTo(new BigDecimal("29.90"));
        }

        @Test
        void alreadyPurchasedItemThrows() {
            CatalogItem item = new CatalogItem();
            item.setId(42L);
            item.setName("Cool MOD");
            item.setPrice(new BigDecimal("29.90"));
            when(catalogItemRepository.findById(42L)).thenReturn(Optional.of(item));
            when(entitlementService.hasPurchasedOrActiveEntitlement(user, 42L)).thenReturn(true);

            Map<String, Object> req = Map.of("item_id", 42, "wallet_recharge", false);

            assertThatThrownBy(() -> orderService.resolveCheckoutFields(req, user))
                    .isInstanceOf(IllegalArgumentException.class)
                    .hasMessageContaining("已购买");
        }

        @Test
        void freeItemThrows() {
            CatalogItem item = new CatalogItem();
            item.setId(42L);
            item.setName("Free MOD");
            item.setPrice(BigDecimal.ZERO);
            when(catalogItemRepository.findById(42L)).thenReturn(Optional.of(item));
            when(entitlementService.hasPurchasedOrActiveEntitlement(user, 42L)).thenReturn(false);

            Map<String, Object> req = Map.of("item_id", 42, "wallet_recharge", false);

            assertThatThrownBy(() -> orderService.resolveCheckoutFields(req, user))
                    .isInstanceOf(IllegalArgumentException.class)
                    .hasMessageContaining("免费");
        }

        @Test
        void noIdentifierThrows() {
            Map<String, Object> req = Map.of("wallet_recharge", false);

            assertThatThrownBy(() -> orderService.resolveCheckoutFields(req, user))
                    .isInstanceOf(IllegalArgumentException.class)
                    .hasMessageContaining("wallet_recharge、plan_id 或 item_id");
        }
    }

    @Nested
    class FulfillOrder {
        @Test
        void walletRechargeCreditsBalance() {
            Order order = buildPaidOrder("OT-W1", "wallet", new BigDecimal("50.00"));
            when(orderRepository.findByOutTradeNoForUpdate("OT-W1")).thenReturn(Optional.of(order));
            when(orderRepository.save(any())).thenAnswer(inv -> inv.getArgument(0));
            Transaction txn = new Transaction();
            txn.setId(100L);
            when(walletService.credit(eq(user), eq(new BigDecimal("50.00")), anyString(), anyString(),
                    anyString(), anyString(), any(), anyString())).thenReturn(txn);

            orderService.fulfillOrder("OT-W1");

            verify(walletService).credit(eq(user), eq(new BigDecimal("50.00")), eq("alipay_recharge"),
                    anyString(), eq("OT-W1"), eq("OT-W1"), isNull(), anyString());
        }

        @Test
        void planOrderActivatesEntitlementAndGrantsTokens() {
            Order order = buildPaidOrder("OT-P1", "plan", new BigDecimal("199.00"));
            order.setPlanId("pro");
            when(orderRepository.findByOutTradeNoForUpdate("OT-P1")).thenReturn(Optional.of(order));
            when(orderRepository.save(any())).thenAnswer(inv -> inv.getArgument(0));

            PlanTemplate plan = new PlanTemplate();
            plan.setId("pro");
            when(planTemplateRepository.findById("pro")).thenReturn(Optional.of(plan));

            orderService.fulfillOrder("OT-P1");

            verify(walletService).recordExternalPayment(order);
            verify(walletService).recordOrderSpend(order);
            verify(entitlementService).activatePlan(user, plan, "OT-P1");
            verify(walletService).grantPlanMembershipTokenAllowance(order);
        }

        @Test
        void itemOrderCreatesPurchaseAndGrantsEntitlement() {
            Order order = buildPaidOrder("OT-I1", "item", new BigDecimal("29.90"));
            order.setItemId(42L);
            when(orderRepository.findByOutTradeNoForUpdate("OT-I1")).thenReturn(Optional.of(order));
            when(orderRepository.save(any())).thenAnswer(inv -> inv.getArgument(0));

            orderService.fulfillOrder("OT-I1");

            verify(walletService).recordExternalPayment(order);
            verify(walletService).recordOrderSpend(order);
            verify(entitlementService).createPurchase(user, 42L, new BigDecimal("29.90"));
            verify(entitlementService).grantCatalogEntitlement(user, 42L, "OT-I1");
        }

        @Test
        void unknownOrderKindThrows() {
            Order order = buildPaidOrder("OT-X1", "unknown_kind", new BigDecimal("10.00"));
            when(orderRepository.findByOutTradeNoForUpdate("OT-X1")).thenReturn(Optional.of(order));

            assertThatThrownBy(() -> orderService.fulfillOrder("OT-X1"))
                    .isInstanceOf(IllegalStateException.class)
                    .hasMessageContaining("未知订单类型");
        }

        @Test
        void alreadyFulfilledOrderIsNoop() {
            Order order = buildPaidOrder("OT-D1", "item", new BigDecimal("10.00"));
            order.setFulfilled(true);
            when(orderRepository.findByOutTradeNoForUpdate("OT-D1")).thenReturn(Optional.of(order));

            orderService.fulfillOrder("OT-D1");

            verifyNoInteractions(walletService);
            verifyNoInteractions(entitlementService);
        }

        @Test
        void xpFailureDoesNotBlockFulfillment() {
            Order order = buildPaidOrder("OT-XP1", "item", new BigDecimal("10.00"));
            order.setItemId(1L);
            when(orderRepository.findByOutTradeNoForUpdate("OT-XP1")).thenReturn(Optional.of(order));
            when(orderRepository.save(any())).thenAnswer(inv -> inv.getArgument(0));
            doThrow(new RuntimeException("xp error")).when(accountLevelService).applyOrderXp(any());

            orderService.fulfillOrder("OT-XP1");

            verify(webhookDispatcher).publishPaymentPaid(order);
        }
    }

    @Nested
    class ProcessAlipayNotify {
        @Test
        void tradeSuccessFulfillsOrder() {
            Order order = buildPendingOrder("OT-N1", "item", new BigDecimal("10.00"));
            order.setItemId(1L);
            when(orderRepository.findByOutTradeNoForUpdate("OT-N1")).thenReturn(Optional.of(order));
            when(orderRepository.save(any())).thenAnswer(inv -> inv.getArgument(0));

            orderService.processAlipayNotify("OT-N1", "TRADE_SUCCESS", "TN-1", "B-1", new BigDecimal("10.00"));

            verify(orderRepository, atLeastOnce()).save(argThat(o -> "paid".equals(o.getStatus())));
        }

        @Test
        void amountMismatchThrows() {
            Order order = buildPendingOrder("OT-N2", "item", new BigDecimal("10.00"));
            when(orderRepository.findByOutTradeNoForUpdate("OT-N2")).thenReturn(Optional.of(order));

            assertThatThrownBy(() -> orderService.processAlipayNotify("OT-N2", "TRADE_SUCCESS",
                    "TN-2", "B-2", new BigDecimal("5.00")))
                    .isInstanceOf(IllegalArgumentException.class)
                    .hasMessageContaining("金额不匹配");
        }

        @Test
        void nonSuccessStatusIsNoop() {
            orderService.processAlipayNotify("OT-N3", "WAIT_BUYER_PAY", "TN-3", "B-3", null);
            verifyNoInteractions(orderRepository);
        }
    }

    @Nested
    class CancelPendingOrder {
        @Test
        void cancelsOwnPendingOrder() {
            Order order = buildPendingOrder("OT-C1", "item", new BigDecimal("10.00"));
            when(orderRepository.findByOutTradeNoForUpdate("OT-C1")).thenReturn(Optional.of(order));
            when(orderRepository.save(any())).thenAnswer(inv -> inv.getArgument(0));

            boolean result = orderService.cancelPendingOrder(user, "OT-C1");

            assertThat(result).isTrue();
            verify(orderRepository).save(argThat(o -> "closed".equals(o.getStatus())));
        }

        @Test
        void cannotCancelOtherUsersOrder() {
            User other = new User();
            other.setId(999L);
            other.setUsername("other");
            other.setPasswordHash("hash");
            Order order = buildPendingOrder("OT-C2", "item", new BigDecimal("10.00"));
            order.setUser(other);
            when(orderRepository.findByOutTradeNoForUpdate("OT-C2")).thenReturn(Optional.of(order));

            assertThat(orderService.cancelPendingOrder(user, "OT-C2")).isFalse();
        }

        @Test
        void cannotCancelNonPendingOrder() {
            Order order = buildPaidOrder("OT-C3", "item", new BigDecimal("10.00"));
            when(orderRepository.findByOutTradeNoForUpdate("OT-C3")).thenReturn(Optional.of(order));

            assertThat(orderService.cancelPendingOrder(user, "OT-C3")).isFalse();
        }

        @Test
        void nonexistentOrderReturnsFalse() {
            when(orderRepository.findByOutTradeNoForUpdate("OT-C4")).thenReturn(Optional.empty());

            assertThat(orderService.cancelPendingOrder(user, "OT-C4")).isFalse();
        }
    }

    @Nested
    class CloseExpiredPendingOrders {
        @Test
        void closesOrdersOlderThanMaxAge() {
            Order old1 = buildPendingOrder("OT-E1", "item", new BigDecimal("10.00"));
            old1.setCreatedAt(LocalDateTime.now().minusHours(2));
            Order old2 = buildPendingOrder("OT-E2", "item", new BigDecimal("20.00"));
            old2.setCreatedAt(LocalDateTime.now().minusHours(3));
            Order recent = buildPendingOrder("OT-E3", "item", new BigDecimal("30.00"));
            recent.setCreatedAt(LocalDateTime.now());
            Order paid = buildPaidOrder("OT-E4", "item", new BigDecimal("40.00"));
            paid.setCreatedAt(LocalDateTime.now().minusHours(5));

            when(orderRepository.findAll()).thenReturn(List.of(old1, old2, recent, paid));
            when(orderRepository.saveAll(any())).thenAnswer(inv -> inv.getArgument(0));

            int closed = orderService.closeExpiredPendingOrders(Duration.ofHours(1));

            assertThat(closed).isEqualTo(2);
        }
    }

    @Nested
    class ReconcileWithAlipay {
        @Test
        void reconcilesWechatWhenQueryReturnsSuccess() {
            Order order = buildPendingOrder("OT-R1", "item", new BigDecimal("10.00"));
            order.setPayType("wechat_native");
            when(orderRepository.findByOutTradeNoForUpdate("OT-R1")).thenReturn(Optional.of(order));
            when(orderRepository.save(any())).thenAnswer(inv -> inv.getArgument(0));

            Map<String, Object> wx = new HashMap<>();
            wx.put("ok", true);
            wx.put("trade_state", "SUCCESS");
            wx.put("transaction_id", "WX-T1");
            wx.put("payer_total_yuan", new BigDecimal("10.00"));
            when(wechatPayService.queryTransactionByOutTradeNo("OT-R1")).thenReturn(wx);

            orderService.reconcileWithAlipayIfUnfulfilled("OT-R1");

            verifyNoInteractions(alipayService);
            verify(orderRepository, atLeastOnce()).save(argThat(o -> "paid".equals(o.getStatus())));
        }

        @Test
        void skipsWechatWhenQueryNotSuccessful() {
            Order order = buildPendingOrder("OT-R1b", "item", new BigDecimal("10.00"));
            order.setPayType("wechat_native");
            when(orderRepository.findByOutTradeNoForUpdate("OT-R1b")).thenReturn(Optional.of(order));
            when(wechatPayService.queryTransactionByOutTradeNo("OT-R1b")).thenReturn(Map.of("ok", false, "message", "NOTPAY"));

            orderService.reconcileWithAlipayIfUnfulfilled("OT-R1b");

            verifyNoInteractions(alipayService);
            verify(orderRepository, never()).save(any());
        }

        @Test
        void skipsAlreadyFulfilledPaidOrder() {
            Order order = buildPaidOrder("OT-R2", "item", new BigDecimal("10.00"));
            order.setFulfilled(true);
            when(orderRepository.findByOutTradeNoForUpdate("OT-R2")).thenReturn(Optional.of(order));

            orderService.reconcileWithAlipayIfUnfulfilled("OT-R2");

            verifyNoInteractions(alipayService);
            verifyNoInteractions(wechatPayService);
        }

        @Test
        void reconcilesWhenAlipayReturnsTradeSuccess() {
            Order order = buildPendingOrder("OT-R3", "item", new BigDecimal("10.00"));
            when(orderRepository.findByOutTradeNoForUpdate("OT-R3")).thenReturn(Optional.of(order));
            when(orderRepository.save(any())).thenAnswer(inv -> inv.getArgument(0));

            Map<String, Object> queryResult = new HashMap<>();
            queryResult.put("ok", true);
            queryResult.put("trade_status", "TRADE_SUCCESS");
            queryResult.put("trade_no", "TN-R3");
            queryResult.put("buyer_id", "B-R3");
            queryResult.put("total_amount", "10.00");
            when(alipayService.queryOrder("OT-R3")).thenReturn(queryResult);

            orderService.reconcileWithAlipayIfUnfulfilled("OT-R3");

            verify(orderRepository, atLeastOnce()).save(argThat(o -> "paid".equals(o.getStatus())));
            verifyNoInteractions(wechatPayService);
        }

        @Test
        void noopsWhenAlipayQueryFails() {
            Order order = buildPendingOrder("OT-R4", "item", new BigDecimal("10.00"));
            when(orderRepository.findByOutTradeNoForUpdate("OT-R4")).thenReturn(Optional.of(order));

            Map<String, Object> queryResult = Map.of("ok", false, "message", "not found");
            when(alipayService.queryOrder("OT-R4")).thenReturn(queryResult);

            orderService.reconcileWithAlipayIfUnfulfilled("OT-R4");

            verify(orderRepository, never()).save(any());
            verifyNoInteractions(wechatPayService);
        }
    }

    @Nested
    class BackfillPlanMembershipTokenGrants {
        @Test
        void creditsNewAndSkipsExisting() {
            Order o1 = buildPaidOrder("BF-1", "plan", new BigDecimal("199.00"));
            Order o2 = buildPaidOrder("BF-2", "plan", new BigDecimal("99.00"));
            when(orderRepository.findByOrderKindAndFulfilledTrueAndStatus("plan", "paid"))
                    .thenReturn(List.of(o1, o2));

            String idem1 = "wallet:credit:plan_membership_tokens:BF-1:membership-tokens";
            String idem2 = "wallet:credit:plan_membership_tokens:BF-2:membership-tokens";
            when(transactionRepository.findByIdempotencyKey(idem1)).thenReturn(Optional.empty());
            when(transactionRepository.findByIdempotencyKey(idem2)).thenReturn(Optional.of(new Transaction()));

            Map<String, Object> result = orderService.backfillPlanMembershipTokenGrants();

            assertThat(result.get("newly_credited")).isEqualTo(1);
            assertThat(result.get("already_had_token_grant")).isEqualTo(1);
            verify(walletService).grantPlanMembershipTokenAllowance(o1);
            verify(walletService, never()).grantPlanMembershipTokenAllowance(o2);
        }
    }
}
