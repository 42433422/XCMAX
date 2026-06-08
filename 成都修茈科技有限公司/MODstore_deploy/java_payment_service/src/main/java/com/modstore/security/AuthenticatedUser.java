package com.modstore.security;

public record AuthenticatedUser(Long id, String username, boolean admin) {
}
