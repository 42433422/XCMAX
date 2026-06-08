package com.modstore.security;

import io.jsonwebtoken.Claims;
import org.springframework.security.core.GrantedAuthority;
import org.springframework.security.core.authority.SimpleGrantedAuthority;

import java.util.ArrayList;
import java.util.Collection;
import java.util.List;

final class JwtRoleAuthorities {

    private JwtRoleAuthorities() {
    }

    /**
     * 从 JWT claims 解析 {@code roles}（字符串数组）；元素 {@code ADMIN} 映射为 {@code ROLE_ADMIN}。
     */
    static List<GrantedAuthority> fromClaims(Claims claims) {
        List<GrantedAuthority> out = new ArrayList<>();
        Object raw = claims.get("roles");
        if (raw instanceof Collection<?> coll) {
            for (Object o : coll) {
                if (o instanceof String s) {
                    addRole(out, s);
                }
            }
        } else if (raw instanceof String s && !s.isBlank()) {
            addRole(out, s);
        }
        return out;
    }

    private static void addRole(List<GrantedAuthority> out, String name) {
        String n = name.trim();
        if (n.isEmpty()) {
            return;
        }
        String authority = n.startsWith("ROLE_") ? n : "ROLE_" + n;
        out.add(new SimpleGrantedAuthority(authority));
    }
}
