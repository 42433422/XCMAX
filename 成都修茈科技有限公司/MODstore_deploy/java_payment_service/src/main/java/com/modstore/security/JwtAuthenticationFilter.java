package com.modstore.security;

import io.jsonwebtoken.Claims;
import io.jsonwebtoken.JwtException;
import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.security.Keys;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.GrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.web.authentication.WebAuthenticationDetailsSource;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import javax.crypto.SecretKey;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.List;

@Component
public class JwtAuthenticationFilter extends OncePerRequestFilter {

    private static final Logger log = LoggerFactory.getLogger(JwtAuthenticationFilter.class);

    private final SecretKey signingKey;

    public JwtAuthenticationFilter(@Value("${jwt.secret}") String jwtSecret) {
        byte[] secretBytes = jwtSecret.getBytes(StandardCharsets.UTF_8);
        if (secretBytes.length < 32) {
            throw new IllegalStateException("jwt.secret / MODSTORE_JWT_SECRET must be at least 32 bytes for HS256");
        }
        this.signingKey = Keys.hmacShaKeyFor(secretBytes);
    }

    @Override
    protected void doFilterInternal(
            HttpServletRequest request,
            HttpServletResponse response,
            FilterChain filterChain
    ) throws ServletException, IOException {
        String header = request.getHeader("Authorization");
        if (header == null || !header.startsWith("Bearer ")) {
            filterChain.doFilter(request, response);
            return;
        }

        String token = header.substring("Bearer ".length()).trim();
        try {
            Claims claims = Jwts.parser()
                    .verifyWith(signingKey)
                    .build()
                    .parseSignedClaims(token)
                    .getPayload();
            if (!"access".equals(claims.get("type", String.class))) {
                filterChain.doFilter(request, response);
                return;
            }
            Long userId = Long.valueOf(claims.getSubject());
            String username = claims.get("username", String.class);
            List<GrantedAuthority> authorities = JwtRoleAuthorities.fromClaims(claims);
            boolean admin = authorities.stream().anyMatch(a -> "ROLE_ADMIN".equals(a.getAuthority()))
                    || "admin".equalsIgnoreCase(username);
            AuthenticatedUser principal = new AuthenticatedUser(userId, username, admin);
            UsernamePasswordAuthenticationToken authentication =
                    new UsernamePasswordAuthenticationToken(principal, null, authorities);
            authentication.setDetails(new WebAuthenticationDetailsSource().buildDetails(request));
            SecurityContextHolder.getContext().setAuthentication(authentication);
        } catch (JwtException | IllegalArgumentException e) {
            SecurityContextHolder.clearContext();
            log.warn(
                    "JWT rejected for {} {}: {} (check MODSTORE_JWT_SECRET matches Python / token not expired / type=access)",
                    request.getMethod(),
                    request.getRequestURI(),
                    e.getMessage()
            );
        }

        filterChain.doFilter(request, response);
    }
}
