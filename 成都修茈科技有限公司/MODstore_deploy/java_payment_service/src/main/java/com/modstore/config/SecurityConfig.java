package com.modstore.config;

import com.modstore.security.JwtAuthenticationFilter;
import lombok.RequiredArgsConstructor;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.http.MediaType;
import org.springframework.security.authentication.AnonymousAuthenticationToken;
import org.springframework.security.core.AuthenticationException;
import org.springframework.http.HttpMethod;
import org.springframework.security.config.annotation.method.configuration.EnableMethodSecurity;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.annotation.web.configuration.EnableWebSecurity;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.security.web.authentication.UsernamePasswordAuthenticationFilter;

import java.nio.charset.StandardCharsets;

@Configuration
@EnableWebSecurity
@EnableMethodSecurity
@RequiredArgsConstructor
public class SecurityConfig {

    private final JwtAuthenticationFilter jwtAuthenticationFilter;
    
    @Bean
    public SecurityFilterChain securityFilterChain(HttpSecurity http) throws Exception {
        http
            .csrf(csrf -> csrf.disable())
            .sessionManagement(session -> session.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
            .authorizeHttpRequests(authorize -> authorize
                .requestMatchers("/api/payment/notify/alipay", "/api/payment/notify/wechat").permitAll()
                .requestMatchers("/api/internal/payment/**").permitAll()
                .requestMatchers("/api/payment/plans").permitAll()
                .requestMatchers("/actuator/health", "/actuator/info", "/actuator/prometheus").permitAll()
                .requestMatchers("/v3/api-docs/**", "/swagger-ui/**", "/swagger-ui.html").permitAll()
                .requestMatchers("/api/refunds/admin/**").hasRole("ADMIN")
                .requestMatchers("/api/webhooks/admin/**").hasRole("ADMIN")
                .requestMatchers(HttpMethod.POST, "/api/payment/reconcile/**").hasRole("ADMIN")
                .requestMatchers(HttpMethod.POST, "/api/payment/refund").hasRole("ADMIN")
                .requestMatchers("/api/**").authenticated()
                .anyRequest().permitAll()
            )
            // 未携带有效 JWT 访问 /api/**：统一 JSON 401（与 Python 网关行为一致，便于前端刷新 token）
            .exceptionHandling(ex -> ex
                .authenticationEntryPoint(
                        (HttpServletRequest request, HttpServletResponse response, AuthenticationException ignored) -> {
                            response.setStatus(HttpServletResponse.SC_UNAUTHORIZED);
                            response.setContentType(MediaType.APPLICATION_JSON_VALUE);
                            response.setCharacterEncoding(StandardCharsets.UTF_8.name());
                            response.getWriter().write("{\"detail\":\"未登录或登录已过期\"}");
                        })
                // 已登录但权限不足：匿名误匹配到受保护资源时 Spring 常给 403，与前端对 401 续期逻辑不一致
                .accessDeniedHandler((request, response, accessDeniedException) -> {
                    var auth = SecurityContextHolder.getContext().getAuthentication();
                    if (auth == null || auth instanceof AnonymousAuthenticationToken) {
                        response.setStatus(HttpServletResponse.SC_UNAUTHORIZED);
                        response.setContentType(MediaType.APPLICATION_JSON_VALUE);
                        response.setCharacterEncoding(StandardCharsets.UTF_8.name());
                        response.getWriter().write("{\"detail\":\"未登录或登录已过期\"}");
                    } else {
                        response.setStatus(HttpServletResponse.SC_FORBIDDEN);
                        response.setContentType(MediaType.APPLICATION_JSON_VALUE);
                        response.setCharacterEncoding(StandardCharsets.UTF_8.name());
                        response.getWriter().write("{\"detail\":\"禁止访问\"}");
                    }
                }))
            .addFilterBefore(jwtAuthenticationFilter, UsernamePasswordAuthenticationFilter.class);
        
        return http.build();
    }
}
