package com.modstore.service;

import com.modstore.model.AccountExperienceLedger;
import com.modstore.model.User;
import com.modstore.repository.AccountExperienceLedgerRepository;
import com.modstore.repository.UserRepository;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.math.BigDecimal;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class AccountLevelServiceLlmXpTest {

    @Mock
    private AccountExperienceLedgerRepository ledgerRepository;

    @Mock
    private UserRepository userRepository;

    @InjectMocks
    private AccountLevelService accountLevelService;

    @Test
    void applyLlmConsumptionXp_grantsAndIdempotent() {
        String billingId = "llm_test:settle";
        User user = new User();
        user.setId(10L);
        user.setExperience(0L);

        when(ledgerRepository.findBySourceTypeAndSourceOrderId("llm_billed", billingId))
                .thenReturn(Optional.empty())
                .thenReturn(Optional.of(new AccountExperienceLedger()));
        when(ledgerRepository.save(any(AccountExperienceLedger.class))).thenAnswer(inv -> inv.getArgument(0));
        when(userRepository.findById(10L)).thenReturn(Optional.of(user));

        long first = accountLevelService.applyLlmConsumptionXp(10L, billingId, new BigDecimal("0.15"), "desc");
        assertThat(first).isEqualTo(15L);
        assertThat(user.getExperience()).isEqualTo(15L);

        long second = accountLevelService.applyLlmConsumptionXp(10L, billingId, new BigDecimal("0.15"), "desc");
        assertThat(second).isEqualTo(0L);
        verify(ledgerRepository, times(1)).save(any(AccountExperienceLedger.class));
    }
}
