package com.modstore.service;

import com.modstore.model.AssetInstallCommand;
import com.modstore.model.CatalogItem;
import com.modstore.model.Order;
import com.modstore.model.Purchase;
import com.modstore.model.User;
import com.modstore.repository.AssetInstallCommandRepository;
import com.modstore.repository.CatalogItemRepository;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.util.List;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class AssetInstallCommandServiceTest {

    @Mock AssetInstallCommandRepository commandRepository;
    @Mock CatalogItemRepository catalogItemRepository;
    @InjectMocks AssetInstallCommandService service;

    @Test
    void queuesOneDurableCommandWithPythonCompatibleIdempotencyKey() {
        User user = new User();
        user.setId(7L);
        Order order = new Order();
        order.setUser(user);
        order.setItemId(9L);
        order.setOutTradeNo("ORDER-1");
        Purchase purchase = new Purchase();
        purchase.setId(11L);
        CatalogItem item = new CatalogItem();
        item.setSha256("a".repeat(64));
        when(catalogItemRepository.findById(9L)).thenReturn(Optional.of(item));
        when(commandRepository.findByIdempotencyKey(any())).thenReturn(Optional.empty());
        when(commandRepository.save(any())).thenAnswer(invocation -> invocation.getArgument(0));

        Optional<AssetInstallCommand> result = service.queuePaidItem(order, purchase);

        assertThat(result).isPresent();
        ArgumentCaptor<AssetInstallCommand> captor = ArgumentCaptor.forClass(AssetInstallCommand.class);
        verify(commandRepository).save(captor.capture());
        AssetInstallCommand command = captor.getValue();
        assertThat(command.getInstallationId()).isEqualTo("*");
        assertThat(command.getStatus()).isEqualTo("pending");
        assertThat(command.getSourceEventId()).isEqualTo("payment.paid:ORDER-1");
        assertThat(command.getIdempotencyKey()).isEqualTo(AssetInstallCommandService.sha256Hex(
                "asset-install:7:11:*:payment_callback:payment.paid:ORDER-1"
        ));
    }

    @Test
    void refusesCatalogArtifactWithoutVerifiableSha() {
        User user = new User();
        user.setId(7L);
        Order order = new Order();
        order.setUser(user);
        order.setItemId(9L);
        order.setOutTradeNo("ORDER-2");
        Purchase purchase = new Purchase();
        purchase.setId(12L);
        CatalogItem item = new CatalogItem();
        item.setSha256("");
        when(catalogItemRepository.findById(9L)).thenReturn(Optional.of(item));

        assertThat(service.queuePaidItem(order, purchase)).isEmpty();
        verify(commandRepository, never()).save(any());
    }

    @Test
    void leavesWorkflowTemplateAsDownloadOnly() {
        User user = new User();
        user.setId(7L);
        Order order = new Order();
        order.setUser(user);
        order.setItemId(9L);
        order.setOutTradeNo("ORDER-TEMPLATE");
        Purchase purchase = new Purchase();
        purchase.setId(13L);
        CatalogItem item = new CatalogItem();
        item.setArtifact("workflow_template");
        item.setSha256("a".repeat(64));
        when(catalogItemRepository.findById(9L)).thenReturn(Optional.of(item));

        assertThat(service.queuePaidItem(order, purchase)).isEmpty();
        verify(commandRepository, never()).save(any());
    }

    @Test
    void revokesOpenCommandsAfterRefund() {
        AssetInstallCommand pending = new AssetInstallCommand();
        pending.setStatus("pending");
        when(commandRepository.findBySourceEventIdAndStatusIn(
                "payment.paid:ORDER-3", List.of("pending", "failed", "claimed")
        )).thenReturn(List.of(pending));

        assertThat(service.revokeForOrder("ORDER-3")).isEqualTo(1);
        assertThat(pending.getStatus()).isEqualTo("revoked");
        assertThat(pending.getError()).isEqualTo("payment_refunded");
        verify(commandRepository).saveAll(List.of(pending));
    }
}
