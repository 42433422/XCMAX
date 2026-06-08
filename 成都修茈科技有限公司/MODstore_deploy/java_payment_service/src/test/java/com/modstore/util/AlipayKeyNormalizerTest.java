package com.modstore.util;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class AlipayKeyNormalizerTest {

    @Test
    void stripsPemPublicKeyWrappersAndWhitespace() {
        String inner = "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAx";
        String pem = "-----BEGIN PUBLIC KEY-----\n"
                + inner
                + "\n-----END PUBLIC KEY-----";
        assertThat(AlipayKeyNormalizer.normalize(pem)).isEqualTo(inner);
    }

    @Test
    void literalBackslashNBecomesNewlineThenCollapsed() {
        String withEscaped = "MIIBIj\\nANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAx";
        assertThat(AlipayKeyNormalizer.normalize(withEscaped)).doesNotContain("\\n");
    }
}
