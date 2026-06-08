package com.modstore.service;

import com.modstore.model.User;
import com.modstore.repository.UserRepository;
import com.modstore.security.AuthenticatedUser;
import lombok.RequiredArgsConstructor;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;

@Service
@RequiredArgsConstructor
public class CurrentUserService {

    private final UserRepository userRepository;
    private static final int MAX_USERNAME_LENGTH = 64;

    @Transactional
    public User requireCurrentUser() {
        Authentication authentication = SecurityContextHolder.getContext().getAuthentication();
        if (authentication == null || !(authentication.getPrincipal() instanceof AuthenticatedUser principal)) {
            throw new IllegalStateException("未登录或登录已过期");
        }
        User user = userRepository.findById(principal.id())
                .orElseGet(() -> provisionUser(principal));
        if (principal.admin() && !user.isAdmin()) {
            user.setAdmin(true);
            return userRepository.saveAndFlush(user);
        }
        return user;
    }

    private User provisionUser(AuthenticatedUser principal) {
        User user = new User();
        user.setId(principal.id());
        user.setUsername(uniqueUsername(principal));
        user.setPasswordHash("external-jwt");
        user.setAdmin(principal.admin());
        user.setCreatedAt(LocalDateTime.now());
        return userRepository.saveAndFlush(user);
    }

    private String uniqueUsername(AuthenticatedUser principal) {
        String preferred = normalizeUsername(principal.username(), "user_" + principal.id());
        if (!userRepository.existsByUsername(preferred)) {
            return preferred;
        }
        String base = normalizeUsername(preferred + "_" + principal.id(), "user_" + principal.id());
        if (!userRepository.existsByUsername(base)) {
            return base;
        }
        for (int i = 1; i < 100; i++) {
            String candidate = truncate(base, MAX_USERNAME_LENGTH - 3) + "_" + i;
            if (!userRepository.existsByUsername(candidate)) {
                return candidate;
            }
        }
        return "user_" + principal.id() + "_" + System.currentTimeMillis();
    }

    private String normalizeUsername(String raw, String fallback) {
        String value = raw == null ? "" : raw.trim();
        if (value.isEmpty()) {
            value = fallback;
        }
        value = value.replaceAll("[^A-Za-z0-9_.@-]", "_");
        return truncate(value, MAX_USERNAME_LENGTH);
    }

    private String truncate(String value, int maxLength) {
        if (value.length() <= maxLength) {
            return value;
        }
        return value.substring(0, maxLength);
    }
}
