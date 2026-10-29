package com.modstore.controller;

import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.web.server.ResponseStatusException;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class LlmWalletServiceControllerContractTest {
    @Test void invalidConfiguredPublicKeyIsUnavailableNotAnAuthenticationFailure() {
        var controller = new LlmWalletServiceController(null, null, null, null, null, "invalid", "synthetic", 100);
        assertThatThrownBy(() -> controller.execute("preauthorize", "synthetic", "{}".getBytes()))
                .isInstanceOfSatisfying(ResponseStatusException.class,
                        error -> assertThat(error.getStatusCode()).isEqualTo(HttpStatus.SERVICE_UNAVAILABLE));
    }
}
