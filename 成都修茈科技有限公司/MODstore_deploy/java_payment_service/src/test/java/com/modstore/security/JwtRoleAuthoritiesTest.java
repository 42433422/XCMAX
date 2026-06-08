package com.modstore.security;

import io.jsonwebtoken.Claims;
import io.jsonwebtoken.impl.DefaultClaims;
import org.junit.jupiter.api.Test;
import org.springframework.security.core.GrantedAuthority;

import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

class JwtRoleAuthoritiesTest {

    @Test
    void parsesStringArrayRoles() {
        Claims claims = new DefaultClaims(Map.of("roles", List.of("ADMIN", "STAFF")));
        var auth = JwtRoleAuthorities.fromClaims(claims);
        assertThat(auth.stream().map(GrantedAuthority::getAuthority))
                .containsExactly("ROLE_ADMIN", "ROLE_STAFF");
    }

    @Test
    void prefixesRoleWhenMissing() {
        Claims claims = new DefaultClaims(Map.of("roles", "ADMIN"));
        var auth = JwtRoleAuthorities.fromClaims(claims);
        assertThat(auth).hasSize(1);
        assertThat(auth.get(0).getAuthority()).isEqualTo("ROLE_ADMIN");
    }

    @Test
    void keepsRolePrefix() {
        Claims claims = new DefaultClaims(Map.of("roles", List.of("ROLE_ADMIN")));
        var auth = JwtRoleAuthorities.fromClaims(claims);
        assertThat(auth.get(0).getAuthority()).isEqualTo("ROLE_ADMIN");
    }

    @Test
    void emptyWhenMissing() {
        Claims claims = new DefaultClaims(Map.of());
        assertThat(JwtRoleAuthorities.fromClaims(claims)).isEmpty();
    }
}
